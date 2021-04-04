"""
LUMI sensor devices (GPIO, illuminance)
"""

import logging
import os

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
        if not os.path.exists(device_file):
            try:
                with open('/sys/class/gpio/export', 'w') as f:
                    f.write(str(gpio))
                with open(f'/sys/class/gpio/gpio{gpio}/direction', 'w') as f:
                    f.write('in')
            except OSError as err:
                logger.error(f"Can not setup {name} sensor: {err}")

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
