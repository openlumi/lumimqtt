"""
LUMI button input
"""

import asyncio as aio

from evdev import InputDevice, KeyEvent, categorize, ecodes

from .device import Device


class ButtonAction:
    SINGLE = 'single'
    DOUBLE = 'double'
    TRIPLE = 'triple'
    QUADRUPLE = 'quadruple'
    MANY = 'many'
    HOLD = 'hold'
    DOUBLE_HOLD = 'double_hold'
    TRIPLE_HOLD = 'triple_hold'
    QUADRUPLE_HOLD = 'quadruple_hold'
    MANY_HOLD = 'many_hold'
    RELEASE = 'release'


class Button(Device):
    """
    Button
    """
    MQTT_VALUES = {
        'icon': 'mdi:gesture-double-tap',
    }
    THRESHOLD = 0.3
    PROVIDE_EVENTS = [
        getattr(ButtonAction, x)
        for x in dir(ButtonAction) if not x.startswith('__')
    ]

    def __init__(self, name, device_file, topic, scancodes):
        super().__init__(name, device_file, topic)
        self.ev_device = InputDevice(self.device_file)
        self.scancodes = [ecodes.ecodes[scancode] for scancode in scancodes]

        self.event_queue = None
        self.is_pressed = False
        self.is_sent = False
        self.clicks_done = 0

    async def handle_events(self):
        async for event in self.ev_device.async_read_loop():
            event = categorize(event)
            if isinstance(event, KeyEvent) and (
                not self.scancodes or event.scancode in self.scancodes
            ):
                if event.keystate in [KeyEvent.key_up, KeyEvent.key_down]:
                    await self.event_queue.put(event.keystate)

    async def handle_queue(self, on_click):
        while True:
            if self.is_pressed and not self.is_sent or self.clicks_done:
                try:
                    event = await aio.wait_for(
                        self.event_queue.get(),
                        timeout=self.THRESHOLD,
                    )
                except aio.TimeoutError:
                    action = {
                        (False, 1): ButtonAction.SINGLE,
                        (False, 2): ButtonAction.DOUBLE,
                        (False, 3): ButtonAction.TRIPLE,
                        (False, 4): ButtonAction.QUADRUPLE,
                        (True, 0): ButtonAction.HOLD,
                        (True, 1): ButtonAction.DOUBLE_HOLD,
                        (True, 2): ButtonAction.TRIPLE_HOLD,
                        (True, 3): ButtonAction.QUADRUPLE_HOLD,
                    }.get((self.is_pressed, self.clicks_done))
                    if action is None:
                        if self.clicks_done > 3 and self.is_pressed:
                            action = ButtonAction.MANY_HOLD
                        elif self.clicks_done > 4 and not self.is_pressed:
                            action = ButtonAction.MANY
                        else:
                            raise NotImplementedError('Unknown button state')

                    await on_click(self, action)
                    self.is_sent = self.is_pressed
                    self.clicks_done = 0
                else:
                    if event == KeyEvent.key_up:
                        self.clicks_done += 1
                        self.is_pressed = False
                    elif event == KeyEvent.key_down:
                        self.is_pressed = True
            else:
                event = await self.event_queue.get()
                if event == KeyEvent.key_up:
                    self.is_pressed = False
                    await on_click(self, ButtonAction.RELEASE)
                elif event == KeyEvent.key_down:
                    self.is_pressed = True
                self.is_sent = False

    async def handle(self, on_click):
        self.event_queue = aio.Queue()
        await aio.gather(
            self.handle_events(),
            self.handle_queue(on_click),
        )
