import asyncio as aio
import json
import logging
import os
from uuid import getnode as get_mac

from .__version__ import version
from .lumimqtt import LumiMqtt
from .platform import devices

logger = logging.getLogger(__name__)


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

    for device in devices(config=config.get('binary_sensors', {})):
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
