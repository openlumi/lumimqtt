"""
LUMI light control
"""
import asyncio as aio
import logging
import os

from .device import Device

logger = logging.getLogger(__name__)


class LED(Device):
    """
    LED control
    """
    def __init__(self, name, device_dir):
        brightness_dev = os.path.join(device_dir, 'brightness')
        super().__init__(name, brightness_dev)
        self.brightness = int(self.read_raw(self.device_file))
        max_brightness_dev = os.path.join(device_dir, 'max_brightness')
        self.max_brightness = int(self.read_raw(max_brightness_dev))

    async def write(self, value: int):
        with open(self.device_file, 'w') as f:
            f.write(f'{value}\n')


class Light(Device):
    """
    Light control
    """
    RGB = True
    BRIGHTNESS = True

    def __init__(self, name, devices: dict, topic):
        super().__init__(name, None, topic)
        self.red = LED(f'{name}_red', devices['red'])
        self.green = LED(f'{name}_green', devices['green'])
        self.blue = LED(f'{name}_blue', devices['blue'])

        self.leds = {
            'r': self.red,
            'g': self.green,
            'b': self.blue,
        }

        self.state = {
            'state': 'ON' if any((self.red.brightness,
                                 self.green.brightness,
                                 self.blue.brightness)) else 'OFF',
            'brightness': 255,
            'color': {},
        }
        for c, led in self.leds.items():
            self.state['color'][c] = int(
                led.brightness / led.max_brightness * 255)

    @property
    def topic_set(self):
        return f'{self.topic}/set'

    async def set(self, value: dict, transition_period: float):
        state = value.get('state', self.state['state'])
        color = value.get('color', self.state['color'])
        # have to save to separate variable, to keep it after off
        target_brightness = \
            brightness = value.get('brightness', self.state['brightness'])
        transition = value.get('transition', transition_period)  # seconds
        start_brightness = self.state['brightness']
        start_color = self.state['color']

        if self.state['state'].lower() == 'off':
            start_brightness = 0
            if color['r'] == 0 and color['g'] == 0 and color['b'] == 0:
                color['r'] = color['g'] = color['b'] = 255
        if state.lower() == 'off':
            brightness = 0

        def color_repr(color: dict):
            return f'#{color["r"]:02x}{color["g"]:02x}{color["b"]:02x}'

        logger.info(f'Change light from {self.state["state"]} '
                    f'{start_brightness} {color_repr(start_color)} '
                    f'to {state} {brightness} {color_repr(start_color)}')

        if transition:
            steps = int(12 * transition)
            if steps < 1:
                steps = 1
            delay = transition / steps / 3
            for step_num in range(1, steps):
                for c, led in self.leds.items():
                    step = (color[c] * brightness / 255 -
                            start_color[c] * start_brightness / 255) / steps
                    next_value = (start_color[c] * start_brightness / 255 +
                                  step * step_num) / 255 * led.max_brightness
                    next_value = int(min(max(next_value, 0),
                                         led.max_brightness))  # normalize
                    await led.write(next_value)
                await aio.sleep(delay)

        for c, led in self.leds.items():
            next_value = color[c] / 255 * led.max_brightness * brightness / 255
            next_value = int(min(max(next_value, 0),
                                 led.max_brightness))  # normalize
            await led.write(next_value)

        self.state = {
            'state': state,
            'brightness': target_brightness,
            'color': color,
        }
