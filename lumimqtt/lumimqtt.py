import asyncio as aio
import json
import logging
import typing as ty
from dataclasses import dataclass
from datetime import datetime
from os.path import exists
from subprocess import DEVNULL, CalledProcessError, run

import aio_mqtt
from evdev import InputDevice, KeyEvent, categorize, ecodes  # noqa

from .__version__ import VERSION

logger = logging.getLogger(__name__)


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


@dataclass
class DebounceSensor:
    value: ty.Any
    last_sent: datetime


class Device:
    MQTT_VALUES = None

    def __init__(self, device, name, topic):
        self.name = name
        self.device = device
        self.topic = topic


class Sensor(Device):
    def get_value(self):
        raise NotImplementedError()


class Button(Device):
    MQTT_VALUES = {
        'icon': 'mdi:gesture-double-tap',
    }
    THRESHOLD = 0.3
    PROVIDE_EVENTS = [
        getattr(ButtonAction, x)
        for x in dir(ButtonAction) if not x.startswith('__')
    ]

    def __init__(self, device, name, topic, scancodes=None):
        super().__init__(device, name, topic)
        self.ev_device = InputDevice(self.device)
        self.scancodes = scancodes

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


class Light(Device):
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
            for x in range(steps):
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


class LumiMqtt:
    def __init__(
            self,
            dev_id: str,
            topic_root: str,
            host: str,
            port: int = None,
            user: ty.Optional[str] = None,
            password: ty.Optional[str] = None,
            reconnection_interval: int = 10,
            *,
            sensor_retain: bool,
            sensor_threshold: int,
            sensor_debounce_period: int,
            loop: ty.Optional[aio.AbstractEventLoop] = None,
    ) -> None:
        self.dev_id = dev_id
        self._topic_root = topic_root
        self._topic_lwt = f'{topic_root}/status'
        self._mqtt_host = host
        self._mqtt_port = port
        self._mqtt_user = user
        self._mqtt_password = password

        self._will_message = aio_mqtt.PublishableMessage(
            topic_name=self._topic_lwt,
            payload='offline',
            qos=aio_mqtt.QOSLevel.QOS_1,
            retain=True,
        )

        self._sensor_retain = sensor_retain
        self._sensor_threshold = sensor_threshold
        self._sensor_debounce_period = sensor_debounce_period

        self._reconnection_interval = reconnection_interval
        self._loop = loop or aio.get_event_loop()
        self._client = aio_mqtt.Client(
            loop=self._loop,
            client_id_prefix='lumimqtt_',
        )
        self._tasks = []

        self.sensors: ty.List[Sensor] = []
        self.lights: ty.List[Light] = []
        self.buttons: ty.List[Button] = []

        self._debounce_sensors: ty.Dict[Sensor, DebounceSensor] = {}

    async def start(self):
        self._tasks = [
            self._loop.create_task(self._connect_forever()),
            self._loop.create_task(self._handle_messages()),
            self._loop.create_task(self._periodic_publish()),
            self._loop.create_task(self._handle_buttons()),
        ]
        finished, unfinished = await aio.wait(
            self._tasks,
            return_when=aio.FIRST_COMPLETED,
        )
        for t in unfinished:
            t.cancel()
            try:
                await t
            except aio.CancelledError:
                pass
        for t in finished:
            t.result()

    async def close(self) -> None:
        for task in self._tasks:
            if task.done():
                continue
            task.cancel()
            try:
                await task
            except aio.CancelledError:
                pass
        if self._client.is_connected():
            await self._client.disconnect()

    def register(self, device: Device):
        if not device:
            return
        mapping = {
            Sensor: self.sensors,
            Button: self.buttons,
            Light: self.lights,
        }
        for typ, array in mapping.items():
            if isinstance(device, typ):
                array.append(device)
                break
        else:
            raise NotImplementedError()

    def _get_topic(self, subtopic):
        return f'{self._topic_root}/{subtopic}'

    @property
    def subscribed_topics(self):
        # TODO: add SOUND/TTS topics ?
        return (self._get_topic(light.topic_set) for light in self.lights)

    async def _handle_messages(self) -> None:
        async for message in self._client.delivered_messages(
                f'{self._topic_root}/#',
        ):
            while True:
                if message.topic_name not in self.subscribed_topics:
                    continue
                light: ty.Optional[Light] = None
                for _light in self.lights:
                    if message.topic_name == self._get_topic(_light.topic_set):
                        light = _light
                if not light:
                    logger.error("Invalid topic for light")
                    break

                try:
                    value = json.loads(message.payload)
                except ValueError as e:
                    logger.exception(str(e))
                    break

                try:
                    await light.set(value)
                    await self._client.publish(
                        aio_mqtt.PublishableMessage(
                            topic_name=self._get_topic(light.topic),
                            payload=json.dumps(light.state),
                            qos=aio_mqtt.QOSLevel.QOS_1,
                        ),
                    )
                except aio_mqtt.ConnectionClosedError as e:
                    logger.error("Connection closed", exc_info=e)
                    await self._client.wait_for_connect()
                    continue

                except Exception as e:
                    logger.error(
                        "Unhandled exception during echo message publishing",
                        exc_info=e)
                break

    async def send_config(self):
        device = {
            'identifiers': [
                f'xiaomi_gateway_{self.dev_id}',
            ],
            'name': f'xiaomi_gateway_{self.dev_id}',
            'sw_version': VERSION,
            'model': 'Xiaomi Gateway',
            'manufacturer': 'Xiaomi',
        }

        def get_generic_vals(name):
            return {
                'name': f'{name}_{self.dev_id}',
                'unique_id': f'{name}_{self.dev_id}',
                'device': device,
                'availability_topic': self._topic_lwt,
            }

        # set sensors config
        for sensor in self.sensors:
            await self._client.publish(
                aio_mqtt.PublishableMessage(
                    topic_name=(
                        f'homeassistant/'
                        f"{'binary_' if self._is_binary(sensor) else ''}sensor"
                        f'/{self.dev_id}/{sensor.topic}/config'
                    ),
                    payload=json.dumps({
                        **get_generic_vals(sensor.name),
                        **(sensor.MQTT_VALUES or {}),
                        'state_topic': self._get_topic(sensor.topic),
                    }),
                    qos=aio_mqtt.QOSLevel.QOS_1,
                    retain=True,
                ),
            )

        # set buttons config
        for button in self.buttons:
            base_topic = self._get_topic(button.topic)
            messages = [
                aio_mqtt.PublishableMessage(
                    topic_name=(
                        f'homeassistant/sensor/{self.dev_id}/'
                        f'{button.topic}/config'
                    ),
                    payload=json.dumps({
                        **get_generic_vals(button.name),
                        **(button.MQTT_VALUES or {}),
                        'json_attributes_topic': base_topic,
                        'state_topic': base_topic,
                        'value_template': '{{ value_json.action }}',
                    }),
                    qos=aio_mqtt.QOSLevel.QOS_1,
                    retain=True,
                ),
            ]
            for event in button.PROVIDE_EVENTS:
                messages.append(
                    aio_mqtt.PublishableMessage(
                        topic_name=(
                            f'homeassistant/device_automation/'
                            f'{button.name}_{self.dev_id}/action_{event}/config'
                        ),
                        payload=json.dumps({
                            # device_automation should not have
                            # name and unique_id
                            'device': device,
                            'automation_type': 'trigger',
                            'topic': f'{base_topic}/action',
                            'subtype': event,
                            'payload': event,
                            'type': 'action',
                        }),
                        qos=aio_mqtt.QOSLevel.QOS_1,
                        retain=True,
                    ),
                )
            await aio.gather(*[self._client.publish(m) for m in messages])

        # set LED lights config
        for light in self.lights:
            await self._client.publish(
                aio_mqtt.PublishableMessage(
                    topic_name=f'homeassistant/light/{self.dev_id}/'
                               f'{light.topic}/config',
                    payload=json.dumps({
                        **get_generic_vals(light.name),
                        'schema': 'json',
                        'rgb': light.RGB,
                        'brightness': light.BRIGHTNESS,
                        'state_topic': self._get_topic(light.topic),
                        'command_topic': self._get_topic(light.topic_set),
                    }),
                    qos=aio_mqtt.QOSLevel.QOS_1,
                    retain=True,
                ),
            )

    async def _periodic_publish(self, period=1):
        while True:
            if not self._client.is_connected():
                await aio.sleep(1)
                continue
            for sensor in self.sensors:
                try:
                    value = sensor.get_value()
                    debounce_val = self._debounce_sensors.get(sensor)
                    if self._is_binary(sensor):
                        should_send = (
                            debounce_val is None or value != debounce_val.value
                        )
                    else:
                        should_send = (
                            debounce_val is None or
                            abs(value - debounce_val.value) >=
                            self._sensor_threshold or
                            (
                                datetime.now() - debounce_val.last_sent
                            ).seconds >= self._sensor_debounce_period
                        )

                    if should_send:
                        self._debounce_sensors[sensor] = DebounceSensor(
                            value=value,
                            last_sent=datetime.now(),
                        )
                        await self._client.publish(
                            aio_mqtt.PublishableMessage(
                                topic_name=self._get_topic(sensor.topic),
                                payload=value,
                                qos=aio_mqtt.QOSLevel.QOS_1,
                                retain=self._sensor_retain,
                            ),
                        )
                except (
                    aio_mqtt.ConnectionClosedError,
                    aio_mqtt.ServerDiedError,
                ) as e:
                    logger.error("Connection closed", exc_info=e)
                    await self._client.wait_for_connect()
                    continue
            await aio.sleep(period)

    async def _handle_buttons(self):
        tasks = [
            aio.create_task(button.handle(self._handle_click))
            for button in self.buttons
        ]
        try:
            finished, unfinished = await aio.wait(
                tasks,
                return_when=aio.FIRST_COMPLETED,
            )
        except aio.CancelledError:
            for t in tasks:
                t.cancel()
                try:
                    await t
                except aio.CancelledError:
                    pass
            raise

        for t in unfinished:
            t.cancel()
            try:
                await t
            except aio.CancelledError:
                pass
        for t in finished:
            t.result()

    async def _handle_click(self, button: Button, action: str):
        logger.debug(f'{button} sent "{action}" event')
        await aio.gather(
            self._client.publish(
                aio_mqtt.PublishableMessage(
                    topic_name=self._get_topic(button.topic),
                    payload=json.dumps({'action': action}),
                    qos=aio_mqtt.QOSLevel.QOS_1,
                ),
            ),
            self._client.publish(
                aio_mqtt.PublishableMessage(
                    topic_name=self._get_topic(f'{button.topic}/action'),
                    payload=action,
                    qos=aio_mqtt.QOSLevel.QOS_1,
                ),
            ),
        )
        await self._client.publish(
            aio_mqtt.PublishableMessage(
                topic_name=self._get_topic(button.topic),
                payload=json.dumps({'action': ''}),
                qos=aio_mqtt.QOSLevel.QOS_1,
            ),
        )

    async def _connect_forever(self) -> None:
        while True:
            try:
                connect_result = await self._client.connect(
                    host=self._mqtt_host,
                    port=self._mqtt_port,
                    username=self._mqtt_user,
                    password=self._mqtt_password,
                    client_id=f'lumimqtt_{self.dev_id}',
                    will_message=self._will_message,
                )
                logger.info(f"Connected to {self._mqtt_host}")

                await self._client.publish(
                    aio_mqtt.PublishableMessage(
                        topic_name=self._topic_lwt,
                        payload='online',
                        qos=aio_mqtt.QOSLevel.QOS_1,
                        retain=True,
                    ),
                )

                await self._client.subscribe(*[
                    (t, aio_mqtt.QOSLevel.QOS_1)
                    for t in self.subscribed_topics
                ])
                await self.send_config()

                logger.info("Wait for network interruptions...")
                await connect_result.disconnect_reason
            except aio.CancelledError:
                raise

            except aio_mqtt.AccessRefusedError as e:
                logger.error("Access refused", exc_info=e)
                raise
            except (
                aio_mqtt.ConnectionLostError,
                aio_mqtt.ConnectFailedError,
                aio_mqtt.ServerDiedError,
            ):
                logger.error(
                    "Connection lost. Will retry in %d seconds",
                    self._reconnection_interval,
                )
                await aio.sleep(self._reconnection_interval)

            except aio_mqtt.ConnectionCloseForcedError as e:
                logger.error("Connection close forced", exc_info=e)
                return

            except Exception as e:
                logger.error(
                    "Unhandled exception during connecting",
                    exc_info=e,
                )
                return

            else:
                logger.info("Disconnected")
                return

    @staticmethod
    def _is_binary(sensor):
        return isinstance(sensor, BinarySensor)
