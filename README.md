# api_utils
Sample programs to access the API

## call-api

Here are two programs, one in Python and one in Perl to help with the execution and accessing the data through the API’s.

For either of these programs to function, they expect a file called ~/.shadowserver.api to exist and to contain your API key and secret. As an example:

```
[api]
key = <<API-KEY>>
secret = <<SECRET>>
uri = https://transform.shadowserver.org/api2/
```

If an error like this occurs, it means that the query is going through a lot of data and the timeout in the program should be increased:

```
$ ./call-api.py reports/query '{"report":"united-states", "date":"2020-10-27", "query":{"city":"ashburn"}, "limit":3}' pretty
API Exception: The read operation timed out
```

Additional details can be found at https://github.com/The-Shadowserver-Foundation/api_utils/wiki.

## report-manager

This program utilizes the reports API to maintain a file system tree with the option to send notifications when new reports are downloaded for processing.

Queue options:

 - Apache Kafka
 - Redis
 - STOMP (ActiveMQ, RabbitMQ)

Usage: `report-manager.py /path/to/config.ini [ days ]`

The optional 'days' argument is the number of previous days to download reports for.  The default is 2.

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

 - directory     : top level directory to store reports in
 - min_disk_free : minimum disk free in MB to attempt download (default 512)
 - notifier      : specify a notification queue type [none, stomp, redis, or kafka]
 - url_prefix    : URL prefix replacement for the top level directory for notification messages
 - reports       : optional list of mailing list names you want to filter by
 - type          : optional report type to filter by

If a 'notifier' is configured in the [reports] section, an additional section with a matching
name is required.

Settings:

 - server       : server IP address or host name
 - port         : server port
 - queue        : queue identifier
 - user         : user name (if required)
 - password     : password (if required)


The notification entry is a JSON object that contains a timestamp, report date, report type, and uri:

```
{
   "timestamp" : "2022-09-01 11:32:45",
   "report_date" : "2022-08-31",
   "report_type" : "scan_stun",
   "uri" : "http://myserver/reports/2022/08/31/2022-08-31-scan_stun_example_com-asn.csv"
}
```

Example crontab to check for new downloads once per hour:

    15 * * * * /opt/shadowserver/report-manager.py /opt/shadowserver/reports.ini

