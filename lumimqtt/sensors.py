from os.path import exists
from subprocess import CalledProcessError, DEVNULL, run
import logging

from .device import Device

logger = logging.getLogger(__name__)


class Sensor(Device):
    def get_value(self):
        raise NotImplementedError()


class BinarySensor(Sensor):
    MQTT_VALUES = {}

    def __init__(self, gpio, name, topic, device_class=None):
        device = f"/sys/class/gpio/gpio{gpio}/value"
        super().__init__(device, name, topic)
        if device_class:
            self.MQTT_VALUES['device_class'] = device_class
        if not exists(device):
            try:
                run(
                    ['tee', '/sys/class/gpio/export'],
                    stdout=DEVNULL,
                    input=str(gpio).encode(),
                    check=True,
                )
                run(
                    ['tee', f'/sys/class/gpio/gpio{gpio}/direction'],
                    stdout=DEVNULL,
                    input='in'.encode(),
                    check=True,
                )
            except CalledProcessError as err:
                logger.error(f"Can not setup {name} sensor: {err.stdout}")

    def get_value(self):
        with open(self.device, 'r') as f:
            return 'OFF' if f.read()[:-1] == '0' else 'ON'


class IlluminanceSensor(Sensor):
    COEFFICIENT = 0.25
    MQTT_VALUES = {
        'device_class': 'illuminance',
        'unit_of_measurement': 'lx',
    }

    def get_value(self):
        with open(self.device, 'r') as f:
            data = f.read()[:-1]
            try:
                return int(int(data) * self.COEFFICIENT)
            except ValueError:
                return data
