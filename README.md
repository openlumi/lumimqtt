# MQTT agent for Xiaomi Lumi gateway

The service allow controlling gateway LEDs. sound and illuminance 
sensor over MQTT

## Installation:

    opkg update 
    opkg install python3-pip python3-asyncio python3-evdev
    pip install lumimqtt

## For Update:

    pip install lumimqtt --upgrade

## Config:
Default config should be located in `/etc/lumimqtt.json` or 
can be overridden with `LUMIMQTT_CONFIG` environment variable.

The configuration file is a JSON with the following content:

```json
{
    "mqtt_host": "localhost",
    "mqtt_port": 1883,
    "mqtt_user": "",
    "mqtt_password": "",
    "sensor_threshold": 50,
    "sensor_debounce_period": 60
}
```
Every line is optional. By default LumiMQTT will use the connection
to localhost with the anonymous login.

`sensor_threshold` is a threshold to avoid sending data to MQTT on small 
changes

`sensor_debounce_period` value in seconds to send data despite of the threshold

## Example run command:

$ lumimqtt

### or (in background):

$ lumimqtt &

## To autorun:
To autorun lumimqtt you need a file 
 **/etc/init.d/lumimqtt** with the following content:

    #!/bin/sh /etc/rc.common
    START=98
    USE_PROCD=1
    start_service()
    {
	procd_open_instance

	procd_set_param env LUMIMQTT_CONFIG=/etc/lumimqtt.json
	procd_set_param command python -m lumimqtt
	procd_set_param stdout 1
	procd_set_param stderr 1
	procd_close_instance
	}
