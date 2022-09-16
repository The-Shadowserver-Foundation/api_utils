#!/usr/bin/env python3
"""

report-manager.py : Shadowserver Foundation Report Utility

Usage: report-manager.py /path/to/config.ini [ days ]

The optional 'days' argument is the number of previous days to download reports for.  The
default is 2.

Sample configuration file:

~~~
[reports]
directory = /var/tmp/reports
min_disk_free = 512
notifier = none
url_prefix = http://myserver/reports/

[stomp]
server = 127.0.0.1
port = 61613
user = guest
password = guest
queue = /queue/mytest

[redis]
server = 127.0.0.1
port = 6379
;password = guest
queue = mytest

[kafka]
server = 127.0.0.1
port = 9092
queue = mytest
~~~

The [reports] section is required and must contain the 'directory' key.

Settings:
  directory     : top level directory to store reports in
  min_disk_free : minimum disk free in MB to attempt download (default 512)
  notifier      : specify a notification queue type [none, stomp, redis, or kafka]
  url_prefix    : URL prefix replacement for the top level directory for notification messages

If a 'notifier' is configured in the [reports] section, an additional section with a matching
name is required.

Settings:
  server       : server IP address or host name
  port         : server port
  queue        : queue identifier
  user         : user name (if required)
  password     : password (if required)

The notification entry is a JSON object that contains a timestamp, report date, report type, and uri:

```
{
   "timestamp" : "2022-09-01 11:32:45",
   "report_date" : "2022-08-31",
   "report_type" : "scan_stun",
   "uri" : "http://myserver/reports/2022/08/31/2022-08-31-scan_stun_example_com-asn.csv"
}
```

Example crontab to check for new reports once per hour:

    15 * * * * /opt/shadowserver/report-manager.py /opt/shadowserver/reports.ini

"""

import os
import sys
import json
import syslog
import configparser
import importlib
import shutil
from datetime import datetime, timedelta, timezone
from urllib.request import urlretrieve, urljoin, pathname2url
api = importlib.import_module('call-api')

class StompNotifier:
    """Notification class for the STOMP protocol. """
    def __init__(self, settings):
        import stomp # pip3 install stomp.py

        self.queue = settings['queue']
        self.stomp = stomp.Connection([(settings['server'], settings['port'])])
        if settings.get('username') and settings.get('password'):
            self.stomp.connect(settings['username'], settings['password'], wait=True)
        else:
            self.stomp.connect(wait=True)

    def notify(self, message):
        self.stomp.send(destination=self.queue, body=message)

class RedisNotifier:
    """Notification class for Redis."""
    def __init__(self, settings):
        import redis # pip3 install redis

        self.queue = settings['queue']
        if settings.get('password'):
            self.redis = redis.Redis(host=settings['server'], port=settings['port'], password=settings['password'])
        else:
            self.redis = redis.Redis(host=settings['server'], port=settings['port'])

    def notify(self, message):
        self.redis.rpush(self.queue, message)

class KafkaNotifier:
    """Notification class for Kafka."""
    def __init__(self, settings):
        from kafka import KafkaProducer # pip3 install kafka

        self.queue = settings['queue']
        self.kafka = KafkaProducer(bootstrap_servers="{}:{}".format(settings['server'], settings['port']))

    def notify(self, message):
        self.kafka.send(self.queue, bytes(message, 'utf-8'))

class ReportManager:
    """Report manager implementation."""

    def __init__(self, config_file):
        """Constructor

        Args:
            config_file (str) : Path to the configuration file
        """
        config = configparser.ConfigParser()
        config.read(config_file)

        self.notifier = None
        self.basedir = config.get('reports', 'directory')
        self.threshold = int(config.get('reports', 'min_disk_free', fallback=512)) * 1024 * 1024
        self.url_prefix = config.get('reports', 'url_prefix', fallback=None)
        self.count = 0

        mkdir(self.basedir)

        queue = config.get('reports', 'notifier', fallback='none')
        try:
            if queue == 'none':
                pass
            elif queue == 'stomp':
                self.notifier = StompNotifier(dict(config.items(queue)))
            elif queue == 'redis':
                self.notifier = RedisNotifier(dict(config.items(queue)))
            elif queue == 'kafka':
                self.notifier = KafkaNotifier(dict(config.items(queue)))
            else:
                raise Exception('Unknown type')
        except Exception as e:
            die("Exception: failed to initialize '{}' notifier - {}".format(queue, format(e)))

    def run(self, days=2):
        """Runs the report manager.

        Args:
            days (int) : Number of previous days to process

        Returns:
            nothing
        """
        for i in reversed(range(1,days+1)):
            dt = datetime.now(timezone.utc) - timedelta(days=i)
            self._sync(dt.strftime("%Y-%m-%d"))
        syslog.syslog(F"Completed - {self.count} reports downloaded")

    def _notify(self, report, filename):
        """Send a notification message.

        Args:
            report (dict) : Report details from the API
            filename (str) : Path to the report file

        Returns:
            nothing
        """
        if not self.url_prefix is None:
            path = filename.replace(self.basedir+os.path.sep, '')
            uri = urljoin(self.url_prefix, pathname2url(path))
        else:
            uri = filename
        dt = datetime.now(timezone.utc)
        msg = json.dumps({
            'timestamp': dt.strftime("%Y-%m-%d %H:%M:%S"),
            'report_date': report['timestamp'],
            'report_type': report['type'],
            'uri': uri,
            })
        self.notifier.notify(msg)

    def _download(self, report, directory):
        """Download a report to the specified directory.

        Args:
            report (dict) : Report details from the API
            directory (str) : Directory to store the report in

        Returns:
            nothing
        """
        tmp = os.path.join(directory, "." + report['file'])
        dst = os.path.join(directory, report['file'])
        if not os.path.exists(dst):
            try:
                urlretrieve('https://dl.shadowserver.org/' + report['id'], tmp)
                if os.path.getsize(tmp) > 0:
                    os.rename(tmp, dst)
                    self.count += 1
                    if not self.notifier is None:
                        self._notify(report, dst)
            except Exception as e:
                syslog.syslog("Exception: unable to download {} - {}".format(report['file'], format(e)))

    def _sync(self, date):
        """Store reports in a tree structure (year/month/day).

        Args:
            date (str) : Date to obtain reports for ("YYYY-MM-DD")

        Returns:
            nothing
        """
        # make tree folders as needed
        directory = self.basedir
        for folder in (date[0:4], date[5:7], date[8:10]):
            directory = os.path.join(directory, folder)
            mkdir(directory)

        # obtain report list
        try:
            result = api.api_call('reports/list', { 'date':date })
        except Exception as e:
            die("API Exception: " + format(e))
        try:
            reports = json.loads(result)
        except Exception as e:
            die("Exception: unable to parse output for reports/list {} - {}".format(date, format(e)))

        # download reports
        for report in reports:
            status = list(shutil.disk_usage(directory))
            if status[2] < self.threshold:
                die("Exception: insufficient disk space")
            self._download(report, directory)

def die(message):
    """Log and exit with a message."

    Args:
        message (str) : Message text

    Returns:
        nothing
    """
    syslog.syslog(message)
    sys.exit(message)

def mkdir(path):
    """Create a directory if it does not already exist. Dies on failure.

    Args:
        path (str) : Directory path to create

    Returns:
        nothing
    """
    if not os.path.isdir(path):
        try:
            os.mkdir(path)
        except:
            die("Exception: unable to create directory '" + path + "'")
    return True

if __name__ == '__main__':
    def main():
        if len(sys.argv) < 2:
            sys.exit("Usage: report_manager.py /path/to/config.ini")

        if len(sys.argv) > 2:
            days = int(sys.argv[2])
        else:
            days = 2

        syslog.openlog("report_manager.py " + os.path.basename(sys.argv[1]))
        manager = ReportManager(sys.argv[1])
        manager.run(days)

    main()
