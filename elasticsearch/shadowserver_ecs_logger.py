#!/usr/bin/env python3
#
# Copyright 2023-2025 The Shadowserver Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"): you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#

import sys
import os
import json
import hashlib
import hmac
import re
import csv
import time
import syslog
import configparser
import logging
import ecs_logging
from urllib.request import urlopen, urlretrieve, Request
from datetime import datetime, timedelta, timezone
import dateutil.parser
import redis
import signal

__unlink_on_signal = None

def signal_handler(signum, frame):
    if __unlink_on_signal is not None:
        os.unlink(__unlink_on_signal)
    sys.exit(1)

def set_timestamp(event, field, value):
    """
    Convert timestamp to isoformat.

    param event: An event dictionary
    param field: The source field name
    param value: The source field value
    """
    event['timestamp'] = value.replace(' ', 'T')+'Z'


def set_tags(event, field, value):
    """
    Split tag values into a list.

    param event: An event dictionary
    param field: The source field name
    param value: The source field value
    """
    event['tags'] = re.split('[,;]', value)


def set_labels(event, field, value, args):
    """
    Add a named label from a field value.

    param event: An event dictionary
    param field: The source field name
    param value: The source field value
    param args:  A list of arguments
    """
    if 'labels' not in event:
        event['labels'] = {}
    try:
        event['labels'][args[0]] = value
    except Exception:
        pass

def convert_timestamp(event, field, value, args):
    """
    Convert timestamp to isoformat.

    param event: An event dictionary
    param field: The source field name
    param value: The source field value
    param args:  A list of field(s) to set
    """
    try:
        date = dateutil.parser.parse(value, fuzzy=True)
        if not date.tzinfo:
            date = date.replace(tzinfo=timezone.utc)
        else:
            date = date.astimezone(timezone.utc)
        value = date.isoformat()
        for arg in args:
            event[arg] = value
    except Exception as e:
        pass


class ShadowserverECSLogger:
    """
    Connects to the Shadowserver API to obtain and stream reported events.
    """
    map_url = 'https://interchange.shadowserver.org/elasticsearch/v1/map'
    api_root = 'https://transform.shadowserver.org/api2/'
    dl_root = 'https://dl.shadowserver.org/'
    timeout = 45
    days = 2
    redis_host = '127.0.0.1'
    redis_port = 6379
    redis_db = 0
    redis_password = None
    redis_timeout = 5000
    redis_queue = 'shadowserver-queue'

    functions = {
            'timestamp': set_timestamp,
            'labels': set_labels,
            'tags': set_tags,
            'convert_timestamp': convert_timestamp,
    }
    map_filename = 'map.json'

    def __init__(self, args):
        """
        Initialize the logger.

        :param config_file: path to a configuration file
        """
        if len(args) < 2:
            raise ValueError("Usage: %s /path/to/config.ini [ update ]" % (args[0]))
        if len(args) > 2:
            self.mode = args[2]
        else:
            self.mode = 'run'

        self.config = configparser.ConfigParser()
        self.config.read(args[1])

        self.state_directory = self.config.get('state', 'directory')
        self.apikey = self.config.get('api', 'key')
        self.secret = self.config.get('api', 'secret')
        self.days = int(self.config.get('api', 'days', fallback=self.days))
        self.redis_host = self.config.get('redis', 'host', fallback=self.redis_host)
        self.redis_port = int(self.config.get('redis', 'port', fallback=self.redis_port))
        self.redis_db = int(self.config.get('redis', 'db', fallback=self.redis_db))
        self.redis_queue = self.config.get('redis', 'queue', fallback=self.redis_queue)
        self.redis_password = self.config.get('redis', 'password', fallback=self.redis_password)
        self.max_age = 86400 * (self.days + 5)
        self.logger = logging.getLogger('app')
        self.logger.setLevel(logging.DEBUG)
        self.output = None

        if not os.path.isdir(self.state_directory):
            raise ValueError('state.directory %r does not exist' % (self.state_directory))

        if self.config.getboolean('api', 'auto_update') or self.mode == 'update':
            self.update()

        self.conn = redis.ConnectionPool(host=self.redis_host, port=self.redis_port, db=self.redis_db, password=self.redis_password)
        self._connect(False) 


    def run(self):
        """
        Stream all available events from reports not yet imported.
        """
        if self.mode != 'run':
            return

        map_path = os.path.join(self.state_directory, self.map_filename)
        with open(map_path) as fh:
            self.mapping = json.load(fh)

        date = datetime.now(timezone.utc).date()
        begin = date - timedelta(self.days)
        date_str = f'{begin.isoformat()}:{date.isoformat()}'

        types = None
        request = {'date': date_str}
        if self.config.has_option('api', 'reports'):
            request['reports'] = self.config.get('api', 'reports').split(',')
        if self.config.has_option('api', 'types'):
            types = self.config.get('api', 'types').split(',')

        dst = os.path.join(self.state_directory, 'reports')
        if not os.path.isdir(dst):
            os.mkdir(dst)

        # locate new reports
        global __unlink_on_signal
        reports = self._api_call('reports/list', request)
        if reports is not None:
            for report in reports:
                if types is not None:
                    if report['type'] not in types:
                        continue
                path = os.path.join(dst, report['file'])
                if not os.path.exists(path):
                    if self._download(report, path):
                        __unlink_on_signal = path
                        self._stream_events(report, path)
                        __unlink_on_signal = None

        # expire old files
        for file in os.listdir(dst):
            path = os.path.join(dst, file)
            if os.path.isfile(path):
                fstat = os.stat(path)
                if time.time()-fstat.st_mtime > self.max_age:
                    os.unlink(path)

    def update(self):
        """
        Update the field mapping.
        """
        map_tmp = os.path.join(self.state_directory, '.' + self.map_filename)
        map_path = os.path.join(self.state_directory, self.map_filename)

        status = False
        try:
            urlretrieve(self.map_url, map_tmp)
            if os.path.getsize(map_tmp) > 0:
                with open(map_tmp) as fh:
                    mapping = json.load(fh)
                status = True
        except Exception as e:
            print("ERROR: Download failed: %s" % (str(e)))

        if status:
            print("INFO: Mapping downloaded successfully")
            os.rename(map_tmp, map_path)
        else:
            if os.path.isfile(map_tmp):
                os.unlink(map_tmp)

        return status

    def _stream_events(self, report, path):
        """
        Import events from the specified report.

        :param report: a dictonary
        :param path: string
        """
        count = 0
        with open(path, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                event = {}
                count += 1
                for field in row:
                    mapped = ".".join(['extra', field])
                    value = row[field]
                    name = ".".join([report['type'], field])
                    if value != "":
                        if name in self.mapping['map']:
                            mapped = self.mapping['map'][name]
                        if field in self.mapping['map']:
                            mapped = self.mapping['map'][field]
                        m = re.match("^\&([^\(]+)\(([^\)]+)\)", mapped)
                        if m:
                            func = m.groups()[0]
                            args = m.groups()[1].split(',')
                            if func in self.functions:
                                self.functions[func](event, field, value, args)
                            continue
                        m = re.match("^\&([^\(]+)", mapped)
                        if m:
                            func = m.groups()[0]
                            if func in self.functions:
                                self.functions[func](event, field, value)
                            continue
                        event[mapped] = value
                event['log.logger'] = report['type']
                event['log.origin.file.name'] = report['file']
                event['log.origin.file.line'] = count
                event['@timestamp'] = event.pop('timestamp')
                try:
                    msg = json.dumps(event, sort_keys=True)
                except Exception:
                    self.logger.exception('Failed to encode event for %s:%d' % (report['file'], count))
                else:
                    sent = False
                    while not sent:
                        try:
                            self.output.lpush(self.redis_queue, msg)
                            sent = True
                        except Exception:
                            self.logger.exception('Failed to send message. Reconnecting.')
                            self._connect(True)

        print("INFO: Processed %d events for %r" % (count, report['file']))

    def _api_call(self, method, request):
        """
        Call the specified api method with a request dictionary.

        :param method: string
        :param request: dictionary
        """
        url = self.api_root + method

        request['apikey'] = self.apikey
        request_string = json.dumps(request)

        secret_bytes = bytes(str(self.secret), 'utf-8')
        request_bytes = bytes(request_string, 'utf-8')

        hmac_generator = hmac.new(secret_bytes, request_bytes, hashlib.sha256)
        hmac2 = hmac_generator.hexdigest()

        result = None
        response = None
        try:
            ua_request = Request(url, data=request_bytes, headers={'HMAC2': hmac2})
            response = urlopen(ua_request, timeout=self.timeout)
        except Exception as e:
            raise ValueException("API Exception %" % format(e))
        try:
            result = json.loads(response.read())
        except Exception as e:
            raise ValueException("Exception: unable to parse output for {}: {}".format(request, format(e)))
        return result

    def _download(self, report, path):
        """
        Download a report.  Returns True on success.

        :param report: dictionary
        :param path: string
        """
        status = False
        try:
            urlretrieve(self.dl_root + report['id'], path)
            if os.path.getsize(path) > 0:
                status = True
        except Exception as e:
            print("ERROR: Download failed: %s" % (str(e)))
            if os.path.exists(path):
                os.unlink(path)
        return status

    def _connect(self, retry):
        """
        Obtains a connection to Redis
        """
        connected = False
        while not connected:
            try:
                self.output = redis.Redis(connection_pool=self.conn, socket_timeout=self.redis_timeout, password=self.redis_password)
                info = self.output.info()
            except redis.ConnectionError:
                if not retry:
                    raise ValueError("Redis connection to %s:%s failed!" % (self.redis_host, self.redis_port))
                time.sleep(20)
            else:
                self.logger.info("Connected successfully to Redis %s at %s:%s!",
                    info['redis_version'], self.redis_host, self.redis_port)
                connected = True
        return self.output

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    sys.exit(ShadowserverECSLogger(sys.argv).run())
