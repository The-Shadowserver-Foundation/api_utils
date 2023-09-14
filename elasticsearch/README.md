# Shadowserver Reports for Elasticsearch

This is an ECS logging script for Shadowserver intelligence reports.  This works with the [Filebeat](https://www.elastic.co/beats/filebeat) shipper.

The script is designed to run from cron and will download and log all events from available reports that have not yet been processed.

The `shadowserver_ecs_logger.py` script is run with the path to the config file:

```
$ python3 shadowserver_ecs_logger.py config.ini
```

A dynamic mapping is used to map the report fields to the [Elastic Common Schema](https://www.elastic.co/guide/en/ecs) (ECS).  The latest mapping will be published as reports are added or revised.

With the `auto_update` option enabled, the script will check for the latest version.

The mapping can be updated separately as follows:

```
$ python3 shadowserver_ecs_logger.py config.ini update
```

### Example config.ini:

```
[general]
state_directory=/var/lib/ecs/state
apikey = <your api key>
secret = <your api secret>
auto_update=true

[device_id]
types=device_id
log=/var/lib/ecs/filebeat
```

The _general_ section contains settings common to all download groups.

* state_directory : path used to store report and mapping details
* apikey : your Shadowserver API key
* secret : your Shadowserver API secret
* auto_update : optional boolean flag to download the latest mapping at startup

Each additional section defines one or more report directives.

* types : optional list of report types to download
* reports : optional list of mailing list names to query
* log : path filebeat will read files from

### Example filebeat.yml

```
filebeat.inputs:

- type: log
  enabled: true
  paths:
    - /var/lib/ecs/filebeat/*.json
  json.keys_under_root: true
  json.overwrite_keys: true
  json.add_error_key: true
  json.expand_keys: true
  publisher_pipeline.disable_host: true

processors:
  - drop_fields:
       fields: ["agent.ephemeral_id", "agent.hostname", "agent.name", "agent.id", "agent.type", "agent.version", "ecs.version", "input.type", "process.name", "process.pid", "process.thread.id", "process.thread.name", "log.original", "log.offset", "log.level", "log.origin.function", "log.origin.file.name", "log.origin.file.line", "log.logger", "log.file.path"]

setup.template.settings:
  index.number_of_shards: 1
  #index.codec: best_compression
  #_source.enabled: false

output.elasticsearch:
  # Array of hosts to connect to.
  hosts: ["localhost:9200"]

  # Protocol - either `http` (default) or `https`.
  protocol: "https"
  ssl.certificate_authorities: ["/opt/elasticsearch-8.9.2/config/certs/http_ca.crt"]

  # Authentication credentials - either API key or username/password.
  #api_key: "beats:OXlsZmQ0b0JnLUTPwjbKCtrtRG06R2tXaUdxdmdURTJLa0Ytdk1Ya1pXdw=="
  username: "elastic"
  password: "YvInisCyhKtwpCkFY2F+"

```
