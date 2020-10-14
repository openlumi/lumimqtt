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
    "mqtt_password": ""
}
```
Every line is optional. By default LumiMQTT will use the connection
to localhost with the anonymous login.
