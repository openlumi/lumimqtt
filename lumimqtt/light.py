"""
LUMI light control
"""

import asyncio as aio

from .device import Device


class Light(Device):
    """
    Light control
    """
    RGB = True
    BRIGHTNESS = True

    def __init__(self, device: dict, name, topic):
        super().__init__(device, name, topic)
        self.led_r = self.device['r']
        self.led_g = self.device['g']
        self.led_b = self.device['b']
        self.pwm_max = int(self.device['pwm_max'])

        state_r = int(open(self.led_r, 'r').read())
        state_g = int(open(self.led_g, 'r').read())
        state_b = int(open(self.led_b, 'r').read())

        self.state = {
            'state': 'ON' if state_r or state_g or state_b else 'OFF',
            'brightness': 255,
            'color': {
                'r': int(state_r / self.pwm_max * 255),
                'g': int(state_g / self.pwm_max * 255),
                'b': int(state_b / self.pwm_max * 255),
            },
        }

    @property
    def topic_set(self):
        return f'{self.topic}/set'

    async def write(self, value: dict):
        state = value.get('state', self.state['state'])
        color = value.get('color', self.state['color'])
        brightness = value.get('brightness', self.state['brightness'])

        for c, file in [
            ('r', self.led_r),
            ('g', self.led_g),
            ('b', self.led_b),
        ]:
            pwm_value = \
                int((color[c] * self.pwm_max / 255) * brightness / 255)
            if state.lower() == 'off':
                pwm_value = 0
            if not (0 <= pwm_value <= self.pwm_max):
                pwm_value = 0
            with open(file, 'w+') as f:
                f.write(str(pwm_value))
                f.write('\n')

    async def set(self, value: dict):
        state = value.get('state', self.state['state'])
        color = value.get('color', self.state['color'])
        brightness = value.get('brightness', self.state['brightness'])
        current_brightness = self.state['brightness']
        target_brightness = brightness
        if self.state['state'].lower() == 'off':
            current_brightness = 0
            if color['r'] == 0 and color['g'] == 0 and color['b'] == 0:
                color['r'] = 255
                color['g'] = 255
                color['b'] = 255
        if state.lower() == 'off':
            target_brightness = 0
        transition = value.get('transition', 1)  # seconds
        steps = 12 * round(transition + 0.49)

        if transition:
            start_level = current_brightness

            """ Use brightness or convert brightness_pct """
            end_level = int(target_brightness)

            if start_level == end_level:
                await self.write(value)
                self.state = {
                    'state': state,
                    'brightness': brightness,
                    'color': color,
                }
                return

            """ Calculate number of steps """
            total_range = abs(start_level - end_level)
            fadeout = start_level > end_level

            """ Calculate the delay time """
            step_by = total_range / steps
            delay = transition / steps / 3

            new_level = start_level
            for _ in range(steps):
                if fadeout:
                    new_level = new_level - step_by
                    if new_level < end_level:
                        new_level = end_level
                else:
                    new_level = new_level + step_by
                    if new_level > end_level:
                        new_level = end_level
                new_value = value.copy()
                new_value['brightness'] = new_level
                new_value['state'] = 'ON'
                await self.write(new_value)
                await aio.sleep(delay)
            if new_level != target_brightness:
                new_value = value.copy()
                new_value['brightness'] = target_brightness
                await self.write(new_value)
        else:
            await self.write(value)

        self.state = {
            'state': state,
            'brightness': brightness,
            'color': color,
        }
