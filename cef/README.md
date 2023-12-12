# Shadowserver Reports in Comment Event Format

This is an CEF logging script for Shadowserver intelligence reports. 

The script is designed to run from cron and will download and log all events from available reports that have not yet been processed.

The `shadowserver_cef_logger.py` script is run with the path to the config file:

```
$ python3 shadowserver_cef_logger.py config.ini
```

A dynamic mapping is used to map the report fields to the [Common Event Format](https://www.microfocus.com/documentation/arcsight/arcsight-smartconnectors-8.3/cef-implementation-standard/Content/CEF/Chapter%201%20What%20is%20CEF.htm) (CEF).  The latest mapping will be published as reports are added or revised.

With the `auto_update` option enabled, the script will check for the latest version.

The mapping can be updated separately as follows:

```
$ python3 shadowserver_cef_logger.py config.ini update
```

### Example config.ini:

```
[general]
state_directory=/var/lib/ecs/state
apikey = <your api key>
secret = <your api secret>
auto_update=true

[device_id]
facility=user
types=device_id
```

The _general_ section contains settings common to all download groups.

* state_directory : path used to store report and mapping details
* apikey : your Shadowserver API key
* secret : your Shadowserver API secret
* auto_update : optional boolean flag to download the latest mapping at startup

Each additional section defines one or more report directives.

* facility : syslog facility to use for each message
* types : optional comma separated list of report types to download
* reports : optional comma separated list of mailing list names to query
* device_event_class_id : optional value to use in each message

