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
from urllib.request import urlopen, urlretrieve, Request
from datetime import datetime, timedelta


MAPURL = 'https://interchange.shadowserver.org/cef/v1/map'
APIROOT = 'https://transform.shadowserver.org/api2/'
DLROOT = 'https://dl.shadowserver.org/'
TIMEOUT = 45
MAX_AGE = 86400 * 7  # 7 days


def syslog_facility(name):
    """
    Returns the log facility for the given name.
    Throws an exception if the name is not known.

    :param name: string
    """
    ref = {
            'kern': syslog.LOG_KERN,
            'user': syslog.LOG_USER,
            'mail': syslog.LOG_MAIL,
            'daemon': syslog.LOG_DAEMON,
            'auth': syslog.LOG_AUTH,
            'lpr': syslog.LOG_LPR,
            'news': syslog.LOG_NEWS,
            'uucp': syslog.LOG_UUCP,
            'cron': syslog.LOG_CRON,
            'syslog': syslog.LOG_SYSLOG,
            'local0': syslog.LOG_LOCAL0,
            'local1': syslog.LOG_LOCAL1,
            'local2': syslog.LOG_LOCAL2,
            'local3': syslog.LOG_LOCAL3,
            'local4': syslog.LOG_LOCAL4,
            'local5': syslog.LOG_LOCAL5,
            'local6': syslog.LOG_LOCAL6,
            'local7': syslog.LOG_LOCAL7,
    }
    if name not in ref:
        raise ValueException("Facility %r is unkown." % (name))
    return ref[name]


def cef_severity(row):
    """
    Returns the CEF severity value for the given row.

    :param row: dictionary
    """
    ref = {
        'info': '0',
        'low': '1',
        'medium': '5',
        'high': '8',
        'critical': '10',
    }
    level = ref['info']
    if 'severity' in row and row['severity'] in ref:
        level = ref[row['severity']]
    return level


class ShadowserverCEFLogger:
    """
    Connects to the Shadowserver API to obtain and log reported events in Common Event Format.
    """
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
        self.cef_version = '0'
        self.device_version = '1.0'

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

        date = datetime.today().date()
        daybefore = date - timedelta(2)
        dayafter = date + timedelta(1)
        date_str = f'{daybefore.isoformat()}:{dayafter.isoformat()}'

        for input_name in self.config:
            input_item = self.config[input_name]
            if 'facility' not in input_item:
                continue
            syslog.openlog(logoption=syslog.LOG_PID, facility=syslog_facility(input_item['facility']))
            types = None
            request = {'date': date_str}
            device_id = '100'
            if 'reports' in input_item:
                request['reports'] = input_item['reports'].split(',')
            if 'types' in input_item:
                types = input_item['types'].split(',')
            if 'device_event_class_id' in input_item:
                device_id = input_item['device_event_class_id']

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
                        if report['type'] not in self.mapping:
                            print("WARN: No mapping defined for %r - skipping %r."
                                  % (report['type'], report['file']))
                            continue
                        if self._download(report, path):
                            self._stream_events(report, path, device_id)
                            # truncate the file to conserve space
                            fh = open(path, 'a')
                            fh.truncate(0)
                            fh.close()

            syslog.closelog()

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

    def _stream_events(self, report, path, device_id):
        """
        Import events from the specified report.

        :param report: dictionary
        :param path: string
        :param device_id: string
        """
        count = 0
        with open(path, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            mapping = self.mapping[report['type']]['map']
            for row in reader:
                count += 1
                parts = []
                parts.append("CEF:%s|Shadowserver|Reports|%s|%s|%s|%s|start=%s" %
                             (self.cef_version, self.device_version, device_id, report['type'],
                              cef_severity(row), row['timestamp'].replace(' ', 'T')))
                for field in row:
                    value = row[field]
                    if value != "":
                        if field in mapping:
                            cef = mapping[field]
                            parts.append("%s=%s" % (cef, value))
                            if re.match('^(c6a|cfp|cn|cs|deviceCustomDate|flexDate|flexString)\d$', cef):
                                parts.append("%sLabel:%s" % (cef, field))
                syslog.syslog(" ".join(parts))
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
    sys.exit(ShadowserverCEFLogger(sys.argv).run())
