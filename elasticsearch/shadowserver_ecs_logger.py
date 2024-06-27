#!/usr/bin/env python3
#
# Copyright 2023 The Shadowserver Foundation, Inc.
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


MAPURL = 'https://interchange.shadowserver.org/elasticsearch/v1/map'
APIROOT = 'https://transform.shadowserver.org/api2/'
DLROOT = 'https://dl.shadowserver.org/'
TIMEOUT = 45
MAX_AGE = 86400 * 7  # 7 days


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


class ECSFormatter(ecs_logging.StdlibFormatter):
    """
    Work-around for "Type mismatch at key `@timestamp`: merging dicts".
    """

    def format_to_ecs(self, record):
        result = super().format_to_ecs(record)
        del result['message']  # remove empty element
        result['@timestamp'] = result.pop('timestamp')
        return result


class ShadowserverECSLogger:
    """
    Connects to the Shadowserver API to obtain and stream reported events.
    """
    functions = {
            'timestamp': set_timestamp,
            'labels': set_labels,
            'tags': set_tags,
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

        self.state_directory = self.config.get('general', 'state_directory')
        self.apikey = self.config.get('general', 'apikey')
        self.secret = self.config.get('general', 'secret')

        if not os.path.isdir(self.state_directory):
            raise ValueError('general.state_directory %r does not exist'
                             % (self.state_directory))

        if self.config.getboolean('general', 'auto_update'):
            self.update()

        map_path = os.path.join(self.state_directory, self.map_filename)
        with open(map_path) as fh:
            self.mapping = json.load(fh)

    def run(self):
        """
        Stream all available events from reports not yet imported.

        :param inputs: an InputDefinition object
        :param event_writer: an EventWriter object
        """
        if self.mode != 'run':
            return

        date = datetime.now(timezone.utc).date()
        begin = date - timedelta(2)
        date_str = f'{begin.isoformat()}:{date.isoformat()}'

        for input_name in self.config:
            input_item = self.config[input_name]
            if 'log' not in input_item:
                continue
            logger = logging.getLogger('app')
            logger.setLevel(logging.DEBUG)
            handler = logging.FileHandler(input_item['log'])
            handler.setFormatter(ECSFormatter())
            logger.addHandler(handler)

            types = None
            request = {'date': date_str}
            if 'reports' in input_item:
                request['reports'] = input_item['reports'].split(',')
            if 'types' in input_item:
                types = input_item['types'].split(',')

            # prepare input specific checkpoint directory
            name = os.path.basename(input_name)
            dst = os.path.join(self.state_directory, name)
            if not os.path.isdir(dst):
                os.mkdir(dst)

            # locate new reports
            reports = self._api_call('reports/list', request)
            if reports is not None:
                for report in reports:
                    if types is not None:
                        if report['type'] not in types:
                            continue
                    path = os.path.join(dst, report['file'])
                    if not os.path.exists(path):
                        if self._download(report, path):
                            self._stream_events(logger, report, path)
                            # truncate the file to conserve space
                            fh = open(path, 'a')
                            fh.truncate(0)
                            fh.close()

            # expire old files
            for file in os.listdir(dst):
                path = os.path.join(dst, file)
                if os.path.isfile(path):
                    fstat = os.stat(path)
                    if time.time()-fstat.st_mtime > MAX_AGE:
                        os.unlink(path)

    def update(self):
        """
        Update the field mapping.
        """
        map_tmp = os.path.join(self.state_directory, '.' + self.map_filename)
        map_path = os.path.join(self.state_directory, self.map_filename)

        status = False
        try:
            urlretrieve(MAPURL, map_tmp)
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

    def _stream_events(self, logger, report, path):
        """
        Import events from the specified report.

        :param logger: a Logger object
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
                event['data_stream.dataset'] = report['type']
                logger.info('', extra=event)
        print("INFO: Processed %d events for %r" % (count, report['file']))

    def _api_call(self, method, request):
        """
        Call the specified api method with a request dictionary.

        :param method: string
        :param request: dictionary
        """
        url = APIROOT + method

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
            response = urlopen(ua_request, timeout=TIMEOUT)
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
            urlretrieve(DLROOT + report['id'], path)
            if os.path.getsize(path) > 0:
                status = True
        except Exception as e:
            print("ERROR: Download failed: %s" % (str(e)))
            os.unlink(path)
        return status


if __name__ == "__main__":
    sys.exit(ShadowserverECSLogger(sys.argv).run())
