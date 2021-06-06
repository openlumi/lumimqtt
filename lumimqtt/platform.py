"""
LUMI platform specification
"""
import logging
import os

from .button import Button
from .light import Light
from .sensors import BinarySensor, IlluminanceSensor

logger = logging.getLogger(__name__)


def sensors(binary_sensors: dict):
    sensors_ = list()
    for name, device_file in (
            ('illuminance', '/sys/bus/iio/devices/iio:device0/in_voltage5_raw'),
    ):
        sensors_.append(IlluminanceSensor(name=name,
                                          device_file=device_file,
                                          topic=name))

    for binary_sensor, sensor_options in binary_sensors.items():
        sensor_config = {
            'name': binary_sensor,
            'topic': binary_sensor,
            **sensor_options,
        }
        if 'gpio' in sensor_config:
            sensors_.append(BinarySensor(**sensor_config))
        else:
            logger.error(f'GPIO number is not set for {binary_sensor} sensor!')
    return sensors_


def buttons():
    buttons_ = list()
    for name, device_file, scancodes in (
            ('btn0', '/dev/input/event0', ['BTN_0']),
    ):
        buttons_.append(Button(name=name,
                               device_file=device_file,
                               topic=name,
                               scancodes=scancodes))
    return buttons_


def lights():
    led_r = '/sys/class/leds/red'
    led_g = '/sys/class/leds/green'
    led_b = '/sys/class/leds/blue'

    led_r_legacy = '/sys/class/backlight/lumi_r'
    led_g_legacy = '/sys/class/backlight/lumi_g'
    led_b_legacy = '/sys/class/backlight/lumi_b'
    if os.path.exists(led_r_legacy):
        leds = {
            'red': led_r_legacy,
            'green': led_g_legacy,
            'blue': led_b_legacy,
        }
    else:
        leds = {
            'red': led_r,
            'green': led_g,
            'blue': led_b,
        }
    lights_ = list()
    for name, device_dirs in (
            ('light', leds),
    ):
        lights_.append(Light(name=name, devices=device_dirs, topic=name))
    return lights_


def devices(binary_sensors: dict):
    return sensors(binary_sensors) + buttons() + lights()
