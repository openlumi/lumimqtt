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
    led_r = '/sys/class/leds/red/brightness'
    led_g = '/sys/class/leds/green/brightness'
    led_b = '/sys/class/leds/blue/brightness'

    led_r_legacy = '/sys/class/backlight/lumi_r/brightness'
    led_g_legacy = '/sys/class/backlight/lumi_g/brightness'
    led_b_legacy = '/sys/class/backlight/lumi_b/brightness'
    if os.path.exists(led_r_legacy):
        light = {
            'r': led_r_legacy,
            'g': led_g_legacy,
            'b': led_b_legacy,
            'pwm_max': 100,
        }
    else:
        light = {'r': led_r, 'g': led_g, 'b': led_b, 'pwm_max': 255}
    lights_ = list()
    for name, device_file in (
            ('light', light),
    ):
        lights_.append(Light(name=name, devices=light, topic=name))
    return lights_


def devices(config: dict):
    return sensors(config) + buttons() + lights()
