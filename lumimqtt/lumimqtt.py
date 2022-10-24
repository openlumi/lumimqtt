"""
LUMI MQTT handler
"""

import asyncio as aio
import json
import logging
import typing as ty
from dataclasses import dataclass
from datetime import datetime

import aio_mqtt

from .__version__ import version
from .button import Button
from .commands import Command
from .device import Device
from .light import Light
from .sensors import BinarySensor, Sensor

logger = logging.getLogger(__name__)


RECONNECTION_LIMIT = 5


@dataclass
class DebounceSensor:
    value: ty.Any
    last_sent: datetime


class LumiMqtt:
    def __init__(
            self,
            device_id: str,
            topic_root: str,
            host: str,
            port: int = None,
            user: ty.Optional[str] = None,
            password: ty.Optional[str] = None,
            reconnection_interval: int = 10,
            *,
            auto_discovery: bool,
            sensor_retain: bool,
            sensor_threshold: int,
            sensor_debounce_period: int,
            light_transition_period: float,
            light_notification_period: float,
            loop: ty.Optional[aio.AbstractEventLoop] = None,
    ) -> None:
        self.dev_id = device_id
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

        self._auto_discovery = auto_discovery
        self._sensor_retain = sensor_retain
        self._sensor_threshold = sensor_threshold
        self._sensor_debounce_period = sensor_debounce_period
        self._light_transition_period = light_transition_period
        self._light_notification_period = light_notification_period
        self._light_last_sent = None

        self._reconnection_interval = reconnection_interval
        self._loop = loop or aio.get_event_loop()
        self._client = aio_mqtt.Client(
            loop=self._loop,
            client_id_prefix='lumimqtt_',
        )
        self._tasks: ty.List[aio.Future] = []

        self.sensors: ty.List[Sensor] = []
        self.lights: ty.List[Light] = []
        self.buttons: ty.List[Button] = []
        self.custom_commands: ty.List[Command] = []

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
        mapping: dict[type, list] = {
            Sensor: self.sensors,
            Button: self.buttons,
            Light: self.lights,
            Command: self.custom_commands,
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
        return [self._get_topic(light.topic_set) for light in self.lights] + \
            [self._get_topic(cmd.topic_set) for cmd in self.custom_commands]

    async def _command_handler(self, command: Command, value):
        await command.set(value)
        reconnection_counter = 0
        while True:
            try:
                await self._client.publish(
                    aio_mqtt.PublishableMessage(
                        topic_name=self._get_topic(command.topic),
                        payload='OFF',
                        qos=aio_mqtt.QOSLevel.QOS_1,
                    ),
                )
                return
            except aio_mqtt.ConnectionClosedError:
                logger.exception("Connection closed")
                reconnection_counter += 1
                if reconnection_counter >= RECONNECTION_LIMIT:
                    raise
                await self._client.wait_for_connect()

    async def _light_handler(self, light: Light, value):
        await light.set(value, self._light_transition_period)
        reconnection_counter = 0
        while True:
            try:
                await self._publish_light(light)
                return
            except aio_mqtt.ConnectionClosedError:
                logger.exception("Connection closed")
                reconnection_counter += 1
                if reconnection_counter >= RECONNECTION_LIMIT:
                    raise
                await self._client.wait_for_connect()

    async def _handle_messages(self) -> None:
        running_message_tasks: list[aio.Task] = []
        try:
            async for message in self._client.delivered_messages(
                    f'{self._topic_root}/#',
            ):
                for task in running_message_tasks:
                    if task.done():
                        try:
                            task.result()
                        except Exception:
                            logger.exception(
                                "Unhandled exception during echo "
                                "message publishing",
                            )
                        finally:
                            running_message_tasks.remove(task)
                if message.topic_name not in self.subscribed_topics:
                    logger.error("Invalid topic for light")
                    continue
                light: ty.Optional[Light] = None
                for _light in self.lights:
                    if message.topic_name == self._get_topic(_light.topic_set):
                        light = _light
                if light:
                    try:
                        value = json.loads(message.payload)
                    except ValueError as e:
                        logger.exception(str(e))
                        continue
                    new_light_task = self._loop.create_task(self._light_handler(light, value))
                    running_message_tasks.append(new_light_task)
                    continue
                command: ty.Optional[Command] = None
                for _command in self.custom_commands:
                    if message.topic_name == self._get_topic(
                            _command.topic_set,
                    ):
                        command = _command
                if command:
                    try:
                        value = json.loads(message.payload)
                    except ValueError:
                        value = message.payload.decode()
                    new_command_task = self._loop.create_task(self._command_handler(command, value))
                    running_message_tasks.append(new_command_task)
        except aio.CancelledError:
            for task in running_message_tasks:
                if task.done():
                    try:
                        task.result()
                    except Exception:
                        pass
                else:
                    task.cancel()
                    try:
                        await task
                    except (Exception, aio.CancelledError):
                        pass

    async def send_config(self):
        device = {
            'identifiers': [
                f'xiaomi_gateway_{self.dev_id}',
            ],
            'name': f'xiaomi_gateway_{self.dev_id}',
            'sw_version': version,
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
                        'color_mode': True,
                        'supported_color_modes': [light.COLOR_MODE],
                        'brightness': light.BRIGHTNESS,
                        'state_topic': self._get_topic(light.topic),
                        'command_topic': self._get_topic(light.topic_set),
                    }),
                    qos=aio_mqtt.QOSLevel.QOS_1,
                    retain=True,
                ),
            )
        for command in self.custom_commands:
            await self._client.publish(
                aio_mqtt.PublishableMessage(
                    topic_name=f'homeassistant/switch/'
                               f'{self.dev_id}_{command.name}/config',
                    payload=json.dumps({
                        **get_generic_vals(command.name),
                        'state_topic': self._get_topic(command.topic),
                        'command_topic': self._get_topic(command.topic_set),
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
            try:
                for sensor in self.sensors:
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
                        await self._publish_sensor(sensor, value)

                for light in self.lights:
                    now = datetime.now()
                    should_send = (
                        self._light_last_sent is None or
                        (now - self._light_last_sent).seconds >=
                        self._light_notification_period
                    )
                    if should_send:
                        await self._publish_light(light)
                        self._light_last_sent = datetime.now()
            except (
                aio_mqtt.ConnectionClosedError,
                aio_mqtt.ServerDiedError,
            ) as e:
                logger.error("Connection closed", exc_info=e)
                await self._client.wait_for_connect()
                continue

            await aio.sleep(period)

    async def _publish_sensor(self, sensor: Sensor, value=None):
        if value is None:
            value = sensor.get_value()
        await self._client.publish(
            aio_mqtt.PublishableMessage(
                topic_name=self._get_topic(sensor.topic),
                payload=value,
                qos=aio_mqtt.QOSLevel.QOS_1,
                retain=self._sensor_retain,
            ),
        )

    async def _publish_light(self, light: Light):
        await self._client.publish(
            aio_mqtt.PublishableMessage(
                topic_name=self._get_topic(light.topic),
                payload=json.dumps(light.state),
                qos=aio_mqtt.QOSLevel.QOS_1,
            ),
        )

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
                client_id = f'lumimqtt_{self.dev_id}'
                connect_result = await self._client.connect(
                    host=self._mqtt_host,
                    port=self._mqtt_port,
                    username=self._mqtt_user,
                    password=self._mqtt_password,
                    client_id=client_id,
                    will_message=self._will_message,
                )
                logger.info(
                    f"Connected to {self._mqtt_host} with client id "
                    f"'{client_id}'",
                )

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
                if self._auto_discovery:
                    await self.send_config()

                for light in self.lights:
                    await self._publish_light(light)

                for sensor in self.sensors:
                    await self._publish_sensor(sensor)

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
