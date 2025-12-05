# Shadowserver Reports for Elasticsearch

This is an ECS logging script for Shadowserver intelligence reports.  This script uses [Redis](https://redis.io/) to queue events for [Logstash](https://www.elastic.co/logstash).

The script is designed to run from cron (e.g. daily) and will download and log all events from available reports that have not yet been processed.

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
[api]
key = c6603b1b-ed7f-4dc8-a47f-b45cae9d1a
secret = pp2be1XZmBp
auto_update=true

[state]
directory=/var/lib/ecs/state

[redis]
host=127.0.0.1
port=6379
queue=shadowserver-queue
```

The _api_ section contains settings to fetch the reports.

* key : your Shadowserver API key (required)
* secret : your Shadowserver API secret (required)
* auto_update : optional boolean flag to download the latest mapping at startup
* types : optional comma separated list of report types to download
* reports : optional comma separated list of mailing list names to query
* days : optional number of days to query for reports (default `2`)

The _state_ section contains settings for maintaining state.

* directory : path used to store report and mapping details (required)

The _redis_ section contains settings for Redis.

* host : host or IP address (default `127.0.0.1`)
* port : port (default `6379`)
* db : db number (default `0`)
* password : optional password string
* timeout : write timeout in ms (default `5000`)
* queue : queue name (default `shadowserver-queue`)


### Example Logstash setup:

This example presumes that elasticsearch, logstash, and redis are on the same host.  Individual settings will need to be tailored to your environment.

as elastic:

```
  cd /opt/logstash
  mv config/pipelines.yml config/pipelines.yml.orig
  echo '- pipeline.id: shadowserver' >> config/pipelines.yml
  echo '  path.config: "/opt/logstash/config/shadowserver.conf"' >> config/pipelines.yml
```

copy to config/shadowserver.conf:

```
input {
  redis {
    host => "127.0.0.1"
    port => 6379
    db => 0
    data_type => "list"
    key => "shadowserver-queue"
  }
}

filter {
  mutate {
    remove_field => ["__type", "@version", "event"]
  }
  fingerprint {
    source => ["log.origin.file.name", "log.origin.file.line"]
    target => "[@metadata][fingerprint]"
    method => "MURMUR3"
    concatenate_sources => true
  }
}

output {
  elasticsearch {
    hosts => ["https://127.0.0.1:9200"]
    ssl_certificate_authorities => ["/opt/elasticsearch/config/certs/http_ca.crt"]
    index => "ecs-logstash-shadowserver-%{+YYYY.MM}"
    user => "elastic"
    password => "NmxDKvM0+efWHRVqiPW6"
    document_id => "%{[@metadata][fingerprint]}"
  }
}

```

The _fingerprint_ filter is used to de-duplicate events streamed to Elasticsearch.

The _ecs-logstash-_ index prefix is needed so that the built-in _ecs-logstash_ index template is utilized.  Without the template events will likely be skipped due to an exception:

> Limit of total fields [1000] has been exceeded while adding new fields

To further limit the number of fields indexed, the **extra** fields can be excluded from search by cloning the _ecs-logstash_ template with a new name (_ecs-shadowserver_) and matching pattern (_ecs-shadowserver-*_) with **extra** added as an object with search disabled.

