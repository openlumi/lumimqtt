import asyncio as aio
import json
import logging
import os
from uuid import getnode as get_mac

from .__version__ import version
from .lumimqtt import LumiMqtt
from .platform import devices

logger = logging.getLogger(__name__)


def read_mac():
    # We try to read mac address from wlan0 interface at first
    # if the file is absent or empty, use generic uuid.getnode()

    addr_file = '/sys/class/net/wlan0/address'
    try:
        with open(addr_file, 'r') as f:
            mac = f.readline().strip('\n')
        mac = f"0x{mac.replace(':', '')}"
    except FileNotFoundError:
        mac = get_mac()
        if (mac >> 40) % 2:
            logger.error("Can't get a valid mac, use randomly generated one")
        mac = hex(mac)

    return mac


def main():
    logging.basicConfig(level='INFO')
    loop = aio.new_event_loop()

    os.environ.setdefault('LUMIMQTT_CONFIG', '/etc/lumimqtt.json')
    config = {}
    if os.path.exists(os.environ['LUMIMQTT_CONFIG']):
        try:
            with open(os.environ['LUMIMQTT_CONFIG'], 'r') as f:
                config = json.load(f)
        except FileNotFoundError:
            pass

    device_id = read_mac()
    config = {
        'device_id': device_id,
        'topic_root': 'lumi/{device_id}',
        'mqtt_host': 'localhost',
        'mqtt_port': 1883,
        'sensor_threshold': 50,  # 5% of illuminance sensor
        'sensor_debounce_period': 60,  # 1 minute
        'light_transition_period': 1.0,  # second
        **config,
    }

    topic_root = \
        config['topic_root'].\
        replace('{device_id}', device_id).\
        replace('{MAC}', device_id)  # support old configs
    server = LumiMqtt(
        reconnection_interval=10,
        loop=loop,
        device_id=config['device_id'],
        topic_root=topic_root,
        host=config['mqtt_host'],
        port=config['mqtt_port'],
        user=config.get('mqtt_user'),
        password=config.get('mqtt_password'),
        sensor_retain=config.get('sensor_retain', False),
        sensor_threshold=int(config['sensor_threshold']),
        sensor_debounce_period=int(config['sensor_debounce_period']),
        light_transition_period=float(config['light_transition_period']),
    )

    for device in devices(config.get('binary_sensors', {})):
        server.register(device)

    try:
        logger.info(f'Start lumimqtt {version}')
        loop.run_until_complete(server.start())
    except KeyboardInterrupt:
        pass

    finally:
        loop.run_until_complete(server.close())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


if __name__ == '__main__':
    main()
