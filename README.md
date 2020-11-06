# MQTT agent for Xiaomi Lumi gateway

The service allow controlling gateway LEDs. sound and illuminance 
sensor over MQTT

Default config should be located in `/etc/lumimqtt.json` or 
can be overridden with `LUMIMQTT_CONFIG` environment variable.

Example run command:

```sh 
LUMIMQTT_CONFIG=./lumimqtt.json python3 lumimqtt.py
```

The configuration file is a JSON with the following content:

```json
{
    "mqtt_host": "localhost",
    "mqtt_port": 1883,
    "mqtt_user": "",
    "mqtt_password": "",
    "topic_root": "lumi/{MAC}",
    "sensor_threshold": 50,
    "sensor_debounce_period": 60
}
```
Every line is optional. By default LumiMQTT will use the connection
to localhost with the anonymous login.

`{MAC}` will be automatically replaced by a hex number representing a MAC address.

`sensor_threshold` is a threshold to avoid sending data to MQTT on small 
changes

`sensor_debounce_period` value in seconds to send data despite of the threshold
