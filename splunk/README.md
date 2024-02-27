
# Shadowserver Reports for Splunk

This is a Splunk Modular Input Add-On for indexing Shadowserver intelligence reports.

## Install

From the _Apps_ menu, select _Manage Apps_.

Click the _Install app from file_ button.

Click the _Browse..._ button and select the `shadowserver_reports.spl` file.

Click _Upload_.


## Add Instance

From the _Settings_ menu, select **Data**|Data inputs.

In the list of _Local inputs_ locate _Shadowserver Reports_ and click the **+ Add new** link to the right.

![image](https://github.com/The-Shadowserver-Foundation/api_utils/assets/16844541/b752ffcf-5c27-4001-b99c-297af16be4fa)

The _name_, _API Key_, and _API secret_ fields are required.  

Check the _More settings_ box to set the desired interval to check for reports.  If the _interval_ field is not set, the add-on will only run once.

The interval can be set to `3600` for hourly or `15 * * * *` to check 15 minutes after every hour.

A cron schedule has five elements (from left to right):

    Minute: 0-59
    Hour: 0-23
    Day of the month: 1-31
    Month: 1-12
    Day of the week: 0-6 (where 0 = Sunday)

The destination index may also be set after checking the _More settings_ box.

Multiple instances of the Add-on can be created to partition events into different destinations by specifying _Reports_ and/or _Types_.


## Configuration Example

Instances configured from the web interface are stored in an `inputs.conf` file.  The following is a sample configuration to import the [Device Identification Report](https://www.shadowserver.org/what-we-do/network-reporting/device-identification-report/):

```
[shadowserver_reports://device_id]
api_key = ........-....-....-....-...........
secret = ..........
types = device_id
disabled = 0
```

## Manual Run

The add-on can be run manually as follows:

`(cd $SPLUNK_HOME;bin/splunk cmd splunkd print-modinput-config shadowserver_reports shadowserver_reports://device_id | bin/splunk cmd python etc/apps/shadowserver_reports/bin/shadowserver_reports.py)`

Where `$SPLUNK_HOME` is the directory that Splunk has been installed and `shadowserver_reports://device_id` matches the name of the instance you want to run as configured in `$SPLUNK_HOME/var/run/splunk/confsnapshot/baseline_local/apps/shadowserver_reports/local/inputs.conf`.
