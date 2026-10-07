"""
LUMI platform specification
"""
import logging
import os
import typing as ty

from .button import Button
from .commands import Command
from .device import Device
from .light import Light
from .sensors import BinarySensor, IlluminanceSensor

logger = logging.getLogger(__name__)


def sensors(binary_sensors: dict) -> ty.List[Device]:
    sensors_: ty.List[Device] = []
    for name, device_file in (
            ('illuminance', '/sys/bus/iio/devices/iio:device0/in_voltage5_raw'),
    ):
        if os.path.exists(device_file):
            sensors_.append(IlluminanceSensor(
                name=name,
                device_file=device_file,
                topic=name,
            ))

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


def buttons() -> ty.List[Device]:
    buttons_: ty.List[Device] = []
    for name, device_file, scancodes in (
            ('btn0', '/dev/input/event0', ['BTN_0']),
    ):
        if os.path.exists(device_file):
            buttons_.append(Button(
                name=name,
                device_file=device_file,
                topic=name,
                scancodes=scancodes,
            ))
    return buttons_


def lights() -> ty.List[Device]:
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
    lights_: ty.List[Device] = []
    for name, device_dirs in (
        ('light', leds),
    ):
        if all(os.path.exists(f) for f in device_dirs.values()):
            lights_.append(Light(name=name, devices=device_dirs, topic=name))
    return lights_


def commands(params) -> ty.List[Device]:
    commands_: ty.List[Device] = []
    for topic, command in params.items():
        cmd_config = {
            'name': topic,
            'topic': topic,
            'device_file': command,
        }
        if isinstance(command, dict):
            cmd_config['device_file'] = command.get('command')
            if 'entity_type' in command:
                cmd_config['entity_type'] = command['entity_type']
            if 'auto_discovery' in command:
                cmd_config['auto_discovery'] = command['auto_discovery']

        cmd = Command(**cmd_config)
        if not isinstance(cmd.command, str):
            logger.error(f'Command {topic}: missing or non-string command!')
        elif cmd.entity_type not in ('switch', 'button'):
            logger.error(f'Command {topic}: invalid entity_type!')
        elif not isinstance(cmd.auto_discovery, bool):
            logger.error(f'Command {topic}: invalid auto_discovery!')
        else:
            commands_.append(cmd)
    return commands_


def devices(binary_sensors: dict, custom_commands: dict):
    return sensors(binary_sensors) + buttons() + lights() + \
        commands(custom_commands)
