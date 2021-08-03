# MQTT agent for Xiaomi Lumi gateway

## Description

The service allow controlling gateway LEDs, button, and illuminance 
sensor over MQTT

Default config should be located in `/etc/lumimqtt.json` or 
can be overridden with `LUMIMQTT_CONFIG` environment variable.


## Interaction

### Default devices

|      Action      |         Topic         |                Payload                |                                                          Expected values          |
|:----------------:|:---------------------:|:-------------------------------------:|:---------------------------------------------------------------------------------:|
| Read light state | lumi/&lt;ID&gt;/light       |                                       | {"state": "ON", "brightness": 255, "color": {"r": 255, "g": 0, "b": 0}}     |
| Switch light     | lumi/&lt;ID&gt;/light/set   | {"state": "ON"}                       |                                                                             |
| Set light color  | lumi/&lt;ID&gt;/light/set   | {"color": {"r": 255, "g": 0, "b": 0}} |                                                                             |
| Set brightness   | lumi/&lt;ID&gt;/light/set   | {"brightness": 255}                   |                                                                             |
| Set color or brigthness with 10 seconds transition | lumi/&lt;ID&gt;/light/set | {"color": {"r": 255, "g": 0, "b": 0}, "brightness": 100, "transition": 10} |        |
| Read illuminance | lumi/&lt;ID&gt;/illuminance |                                       | 0-1000                                                                      |
| Button           | lumi/&lt;ID&gt;/btn0/action | | single, double, triple, quadruple, many,<br>hold, double_hold, triple_hold, quadruple_hold, many_hold,<br>release |



### Binary sensors (soldered to GPIO points)

|      Action      |          Topic          | Expected values |
|:----------------:|:-----------------------:|:---------------:|
| Read GPIO sensor | lumi/&lt;ID&gt;/<SENSOR_NAME> | ON/OFF          |


## Run application
Example run command:

```sh 
LUMIMQTT_CONFIG=./lumimqtt.json python3 -m lumimqtt
```

The configuration file is a JSON with the following content:

```json
{
    "mqtt_host": "localhost",
    "mqtt_port": 1883,
    "mqtt_user": "",
    "mqtt_password": "",
    "topic_root": "lumi/{device_id}",
    "auto_discovery": true,
    "sensor_retain": false,
    "sensor_threshold": 50,
    "sensor_debounce_period": 60,
    "light_transition_period": 1.0
}
```
Every line is optional. By default, LumiMQTT will use the connection
to localhost with the anonymous login.

`device_id` **if not provided** will be automatically replaced by a hex number 
representing a MAC address of the first network interface.

`auto_discovery` set to `false` to disable creating autodiscovery topics that
are user by Home Assistant to discover entities.

`sensor_retain` is option to enable storing last sensor value on the broker

`sensor_threshold` is a threshold to avoid sending data to MQTT on small 
changes

`sensor_debounce_period` value in seconds to send data despite the threshold

`light_transition_period` value in seconds to set default transition for light
switching or light change. Use `0` to remove the transition.

You can also use GPIO(s) as binary sensor(s). Add this to configuration:

```json
{
    <your configuration>,
    "binary_sensors": {
        "<sensor name>": {
            "gpio": "<gpio number>",
            "device_class": "<device class>",
            "topic": "<sensor name>"
        }
    }
}
```

Values in `<>` must be replaced.

`gpio` is required, `device_class` and `topic` are optional. By default `topic` is sensor's name.

[List of GPIOs.](https://github.com/openlumi/xiaomi-gateway-openwrt#gpio)
[List of device classes.](https://www.home-assistant.io/integrations/binary_sensor/#device-class)

### Custom commands

You can add an extra section with custom commands that are executed with 
mqtt topics. Every command is exported as a switch entity in Home Assistant.
If json is passed to the set topic, the command will be interpolated with 
the values. Plain text is passed as {text} variable 
```json
{
    <your configuration>,
    "custom_commands": {
      "blink": "for i in 0 255 0 255 0 255 0; do echo $i > /sys/class/leds/{color}/brightness; sleep 1; done",
      "tts": "echo \"Test TTS without MPD component for home assistant\" | python3 -c 'from urllib.parse import quote_plus;from sys import stdin;print(\"wget -O /tmp/tts.mp3 -U Mozilla \\\"http://translate.google.com/translate_tts?q=\"+quote_plus(stdin.read()[:100])+\"&ie=UTF-8&tl=en&total=1&idx=0&client=tw-ob&prev=input&ttsspeed=1\\\" && amixer set Master 200 && mpg123 /tmp/tts.mp3\")' | sh 2> /dev/null",
      "tts_interpolate": "echo \"{text}\" | python3 -c 'from urllib.parse import quote_plus;from sys import stdin;print(\"wget -O /tmp/tts.mp3 -U Mozilla \\\"http://translate.google.com/translate_tts?q=\"+quote_plus(stdin.read()[:100])+\"&ie=UTF-8&tl=en&total=1&idx=0&client=tw-ob&prev=input&ttsspeed=1\\\" && amixer set Master {volume} && mpg123 /tmp/tts.mp3\")' | sh 2> /dev/null",
      "restart_lumimqtt": "/etc/init.d/lumimqtt restart",
      "reboot": "/sbin/reboot"
    }
}
```

#### Usage examples

|             Action             |              Topic             |                   Payload                         |
|:------------------------------:|:------------------------------:|:-------------------------------------------------:|
| Run command "blink"            | lumi/&lt;ID&gt;/blink/set            | {"color": "red"}                            |
| Run command "tts"              | lumi/&lt;ID&gt;/tts/set              | &lt;ANYTHING&gt;                            |
| Run command "tts_interpolate"  | lumi/&lt;ID&gt;/tts_interpolate/set  | {"text": "Hi, it is a test", "volume": 200} |
| Run command "restart_lumimqtt" | lumi/&lt;ID&gt;/restart_lumimqtt/set | &lt;ANYTHING&gt;                            |
| Run command "reboot"           | lumi/&lt;ID&gt;/reboot/set           | &lt;ANYTHING&gt;                            |

## OpenWrt installation

```sh 
opkg update 
opkg install python3-pip python3-asyncio python3-evdev
pip3 install -U lumimqtt
```

To upgrade you can just run

```sh
pip3 install -U lumimqtt
```

## Example run command:

```sh
lumimqtt
```

### or (in background):

```sh
lumimqtt &
```

### Autorun:
To run lumimqtt on start you need a file 
 **/etc/init.d/lumimqtt** with the following content:

```sh
#!/bin/sh /etc/rc.common
START=98
USE_PROCD=1
start_service()
{
    procd_open_instance

    procd_set_param env LUMIMQTT_CONFIG=/etc/lumimqtt.json
    procd_set_param command lumimqtt
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}
```

To install this file on the gateway you can run

```sh
wget https://raw.githubusercontent.com/openlumi/lumimqtt/main/init.d/lumimqtt -O /etc/init.d/lumimqtt
chmod +x /etc/init.d/lumimqtt
/etc/init.d/lumimqtt enable
/etc/init.d/lumimqtt start
```
