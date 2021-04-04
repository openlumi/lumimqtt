"""
LUMI sensor devices (GPIO, illuminance)
"""

from os.path import exists
from subprocess import CalledProcessError, DEVNULL, run
import logging

from .device import Device

logger = logging.getLogger(__name__)


class Sensor(Device):
    """
    Base sensor class
    """
    def get_value(self):
        raise NotImplementedError()


class BinarySensor(Sensor):
    """
    Binary sensor (GPIO)
    """
    MQTT_VALUES = {}

    def __init__(self, name, gpio, topic, device_class=None):
        device_file = f"/sys/class/gpio/gpio{gpio}/value"
        super().__init__(name, device_file, topic)
        if device_class:
            self.MQTT_VALUES['device_class'] = device_class
        if not exists(device_file):
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
        return 'OFF' if self.read_raw() == '0' else 'ON'


class IlluminanceSensor(Sensor):
    """
    Illuminance sensor
    """
    COEFFICIENT = 0.25
    MQTT_VALUES = {
        'device_class': 'illuminance',
        'unit_of_measurement': 'lx',
    }

    def get_value(self):
        raw_value = self.read_raw()
        return int(int(raw_value) * self.COEFFICIENT)
