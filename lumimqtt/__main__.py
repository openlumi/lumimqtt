import asyncio as aio
import json
import logging
import os
import signal
from uuid import getnode as get_mac

from .__version__ import version
from .lumimqtt import LumiMqtt
from .platform import devices

logger = logging.getLogger(__name__)


def read_mac():
    # We try to read mac address from first interface at first
    # if the file is absent or empty, use generic uuid.getnode()
    ifaces = [x for x in sorted(os.listdir('/sys/class/net/')) if x != 'lo']
    if ifaces:
        addr_file = f'/sys/class/net/{ifaces[0]}/address'
        try:
            with open(addr_file, 'r') as f:
                mac = f.readline().strip('\n')
        except FileNotFoundError:
            pass
        else:
            return f"0x{mac.replace(':', '')}"

    mac = get_mac()
    if (mac >> 40) % 2:
        logger.error("Can't get a valid mac, use randomly generated one")
    mac = hex(mac)

    return mac


def signal_handler():
    raise KeyboardInterrupt()


async def amain():
    logging.basicConfig(level='INFO')

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
        'auto_discovery': True,  # create homeassistant discovery topics
        'sensor_threshold': 50,  # 5% of illuminance sensor
        'sensor_debounce_period': 60,  # 1 minute
        'light_transition_period': 1.0,  # second
        'light_notification_period': 60,  # 1 minute
        'legacy_color_mode': True,  # for HA < 2024.4
        **config,
    }

    topic_root = \
        config['topic_root'].\
        replace('{device_id}', device_id).\
        replace('{MAC}', device_id)  # support old configs
    server = LumiMqtt(
        reconnection_interval=10,
        device_id=config['device_id'],
        topic_root=topic_root,
        host=config['mqtt_host'],
        port=config['mqtt_port'],
        user=config.get('mqtt_user'),
        password=config.get('mqtt_password'),
        ca=config.get('mqtt_ca'),
        cert=config.get('mqtt_cert'),
        key=config.get('mqtt_key'),
        auto_discovery=config['auto_discovery'],
        sensor_retain=config.get('sensor_retain', False),
        sensor_threshold=int(config['sensor_threshold']),
        sensor_debounce_period=int(config['sensor_debounce_period']),
        light_transition_period=float(config['light_transition_period']),
        light_notification_period=float(config['light_notification_period']),
        legacy_color_mode=bool(config['legacy_color_mode']),
    )

    for device in devices(
        binary_sensors=config.get('binary_sensors', {}),
        custom_commands=config.get('custom_commands', {}),
    ):
        server.register(device)

    loop = aio.get_running_loop()
    for _signal in (signal.SIGTERM, signal.SIGQUIT, signal.SIGHUP):
        loop.add_signal_handler(_signal, signal_handler)

    try:
        logger.info(f'Start lumimqtt {version}')
        await server.start()
    finally:
        await server.close()


def main():
    try:
        aio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
