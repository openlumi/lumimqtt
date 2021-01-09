import asyncio as aio
import json
import logging
import os
from uuid import getnode as get_mac

from evdev import ecodes  # noqa

from .lumimqtt import LumiMqtt, BinarySensor, IlluminanceSensor, Button, Light
from .__version__ import VERSION

logger = logging.getLogger(__name__)


illuminance_dev = '/sys/bus/iio/devices/iio:device0/in_voltage5_raw'
button_dev = '/dev/input/event0'
led_r = '/sys/class/backlight/lumi_r/brightness'
led_g = '/sys/class/backlight/lumi_g/brightness'
led_b = '/sys/class/backlight/lumi_b/brightness'

SUBTOPIC_BTN = 'btn0'
SUBTOPIC_ILLUMINANCE = 'illuminance'
SUBTOPIC_LIGHT = 'light'


def main():
    logging.basicConfig(level='INFO')
    loop = aio.new_event_loop()

    os.environ.setdefault('LUMIMQTT_CONFIG', '/etc/lumimqtt.json')
    config = {}
    if os.path.exists(os.environ['LUMIMQTT_CONFIG']):
        try:
            with open(os.environ['LUMIMQTT_CONFIG'], 'r') as f:
                config = json.load(f)
        except Exception:
            pass

    dev_id = hex(get_mac())
    config = {
        'topic_root': 'lumi/{MAC}',
        'mqtt_host': 'localhost',
        'mqtt_port': 1883,
        'sensor_threshold': 50,  # 5% of illuminance sensor
        'sensor_debounce_period': 60,  # 1 minute
        **config,
    }

    server = LumiMqtt(
        reconnection_interval=10,
        loop=loop,
        dev_id=dev_id,
        topic_root=config['topic_root'].replace('{MAC}', dev_id),
        host=config['mqtt_host'],
        port=config['mqtt_port'],
        user=config.get('mqtt_user'),
        password=config.get('mqtt_password'),
        sensor_retain=config.get('sensor_retain', False),
        sensor_threshold=int(config['sensor_threshold']),
        sensor_debounce_period=int(config['sensor_debounce_period']),
    )
    server.register(IlluminanceSensor(
        device=illuminance_dev,
        name='illuminance',
        topic=SUBTOPIC_ILLUMINANCE,
    ))
    server.register(Button(
        device=button_dev,
        name='btn0',
        topic=SUBTOPIC_BTN,
        scancodes=[ecodes.BTN_0],
    ))
    server.register(Light(
        device={'r': led_r, 'g': led_g, 'b': led_b},
        name='light',
        topic=SUBTOPIC_LIGHT,
    ))
    if config.get('binary_sensors'):
        for sensor, sensor_options in config['binary_sensors'].items():
            sensor_config = {
                'name': sensor,
                'topic': sensor,
                **sensor_options
            }
            if 'gpio' in sensor_config:
                server.register(BinarySensor(**sensor_config))
            else:
                logger.error(f'GPIO number is not set for {sensor} sensor!')

    try:
        logger.info(f'Start lumimqtt {VERSION}')
        loop.run_until_complete(server.start())
    except KeyboardInterrupt:
        pass

    finally:
        loop.run_until_complete(server.close())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


if __name__ == '__main__':
    main()
