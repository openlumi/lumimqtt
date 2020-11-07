import asyncio as aio
from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
import typing as ty
from uuid import getnode as get_mac

from evdev import InputDevice, categorize, KeyEvent, ecodes  # noqa
import aio_mqtt

logger = logging.getLogger(__name__)

VERSION = '1.0.4'

illuminance_dev = '/sys/bus/iio/devices/iio:device0/in_voltage5_raw'
button_dev = '/dev/input/event0'
led_r = '/sys/class/backlight/lumi_r/brightness'
led_g = '/sys/class/backlight/lumi_g/brightness'
led_b = '/sys/class/backlight/lumi_b/brightness'

SUBTOPIC_BTN = 'btn0'
SUBTOPIC_ILLUMINANCE = 'illuminance'
SUBTOPIC_LIGHT = 'light'


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

    def __init__(self, device, name, topic, scancodes=None):
        super().__init__(device, name, topic)
        self.ev_device = InputDevice(self.device)
        self.scancodes = scancodes

    async def handle(self, on_click):
        async for event in self.ev_device.async_read_loop():
            event = categorize(event)
            if isinstance(event, KeyEvent) and (
                not self.scancodes or event.scancode in self.scancodes
            ):
                if event.keystate == KeyEvent.key_up:
                    await on_click(self)


class Light(Device):
    RGB = True
    BRIGHTNESS = True

    def __init__(self, device: dict, name, topic):
        super().__init__(device, name, topic)
        self.led_r = self.device['r']
        self.led_g = self.device['g']
        self.led_b = self.device['b']
        self.state = {
            'state': 'OFF',
            'brightness': 255,
            'color': {
                'r': 255,
                'g': 255,
                'b': 255,
            },
        }

    @property
    def topic_set(self):
        return f'{self.topic}/set'

    async def set(self, value: dict):
        state = value.get('state', self.state['state'])
        color = value.get('color', self.state['color'])
        brightness = value.get('brightness', self.state['brightness'])

        for c, file in [
            ('r', self.led_r),
            ('g', self.led_g),
            ('b', self.led_b),
        ]:
            pwm_value = int((color[c] * 100 / 255) * brightness / 255)
            if state.lower() == 'off':
                pwm_value = 0
            if not (0 <= pwm_value <= 100):
                pwm_value = 0
            with open(file, 'w+') as f:
                f.write(str(pwm_value))
                f.write('\n')

        self.state = {
            'state': state,
            'brightness': brightness,
            'color': color
        }


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
            sensor_threshold: int,
            sensor_debounce_period: int,
            loop: ty.Optional[aio.AbstractEventLoop] = None
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

        self._sensor_threshold = sensor_threshold
        self._sensor_debounce_period = sensor_debounce_period

        self._reconnection_interval = reconnection_interval
        self._loop = loop or aio.get_event_loop()
        self._client = aio_mqtt.Client(loop=self._loop)
        self._tasks = []

        self.sensors: ty.List[Sensor] = []
        self.lights: ty.List[Light] = []
        self.buttons: ty.List[Button] = []

        self._debounce_sensors: ty.Dict[Sensor, DebounceSensor] = {}

    def start(self):
        self._tasks = [
            self._loop.create_task(self._connect_forever()),
            self._loop.create_task(self._handle_messages()),
            self._loop.create_task(self._periodic_publish()),
            self._loop.create_task(self._handle_buttons()),
        ]

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
                f'{self._topic_root}/#'
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
                            qos=aio_mqtt.QOSLevel.QOS_1
                        )
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
                        f'homeassistant/sensor/{self.dev_id}/'
                        f'{sensor.topic}/config'
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
            await aio.gather(
                self._client.publish(
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
                ),
                self._client.publish(
                    aio_mqtt.PublishableMessage(
                        topic_name=(
                            f'homeassistant/device_automation/'
                            f'{button.name}_{self.dev_id}/action_single/config'
                        ),
                        payload=json.dumps({
                            # device_automation should not have
                            # name and unique_id
                            'device': device,
                            'automation_type': 'trigger',
                            'topic': f'{base_topic}/action',
                            'subtype': 'single',
                            'payload': 'single',
                            'type': 'action',
                        }),
                        qos=aio_mqtt.QOSLevel.QOS_1,
                        retain=True,
                    ),
                ),
            )

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
                                qos=aio_mqtt.QOSLevel.QOS_1
                            )
                        )
                except aio_mqtt.ConnectionClosedError as e:
                    logger.error("Connection closed", exc_info=e)
                    await self._client.wait_for_connect()
                    continue
            await aio.sleep(period)

    async def _handle_buttons(self):
        for button in self.buttons:
            self._tasks.append(
                aio.create_task(button.handle(self._handle_click)),
            )

    async def _handle_click(self, button: Button):
        await aio.gather(
            self._client.publish(
                aio_mqtt.PublishableMessage(
                    topic_name=self._get_topic(button.topic),
                    payload=json.dumps({'action': 'single'}),
                    qos=aio_mqtt.QOSLevel.QOS_1,
                )
            ),
            self._client.publish(
                aio_mqtt.PublishableMessage(
                    topic_name=self._get_topic(f'{button.topic}/action'),
                    payload='single',
                    qos=aio_mqtt.QOSLevel.QOS_1,
                )
            ),
        )
        await self._client.publish(
            aio_mqtt.PublishableMessage(
                topic_name=self._get_topic(button.topic),
                payload=json.dumps({'action': ''}),
                qos=aio_mqtt.QOSLevel.QOS_1,
            )
        ),

    async def _connect_forever(self) -> None:
        while True:
            try:
                connect_result = await self._client.connect(
                    host=self._mqtt_host,
                    port=self._mqtt_port,
                    username=self._mqtt_user,
                    password=self._mqtt_password,
                    will_message=self._will_message,
                )
                logger.info("Connected")

                await self._client.publish(
                    aio_mqtt.PublishableMessage(
                        topic_name=self._topic_lwt,
                        payload='online',
                        qos=aio_mqtt.QOSLevel.QOS_1,
                        retain=True,
                    )
                ),

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

            except (
                aio_mqtt.ConnectionLostError,
                aio_mqtt.ConnectFailedError,
                aio_mqtt.ServerDiedError,
            ) as e:
                logger.error(
                    "Connection lost. Will retry in %d seconds",
                    self._reconnection_interval,
                )
                await aio.sleep(self._reconnection_interval, loop=self._loop)

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


if __name__ == '__main__':
    logging.basicConfig(
        level='DEBUG'
    )
    loop = aio.new_event_loop()

    os.environ.setdefault('LUMIMQTT_CONFIG', '/etc/lumimqtt.json')
    config = {}
    if os.path.exists(os.environ['LUMIMQTT_CONFIG']):
        try:
            with open(os.environ['LUMIMQTT_CONFIG'], 'r') as f:
                config = json.load(f)
        except Exception:
            pass

    dev_id = hex(get_mac())
    config = {
        'topic_root': 'lumi/{MAC}',
        'mqtt_host': 'localhost',
        'mqtt_port': 1883,
        'sensor_threshold': 50,  # 5% of illuminance sensor
        'sensor_debounce_period': 60,  # 1 minute
        **config,
    }

    server = LumiMqtt(
        reconnection_interval=10,
        loop=loop,
        dev_id=dev_id,
        topic_root=config['topic_root'].replace('{MAC}', dev_id),
        host=config['mqtt_host'],
        port=config['mqtt_port'],
        user=config.get('mqtt_user'),
        password=config.get('mqtt_password'),
        sensor_threshold=int(config['sensor_threshold']),
        sensor_debounce_period=int(config['sensor_debounce_period']),
    )
    server.register(IlluminanceSensor(
        device=illuminance_dev,
        name='illuminance',
        topic=SUBTOPIC_ILLUMINANCE,
    ))
    server.register(Button(
        device=button_dev,
        name='btn0',
        topic=SUBTOPIC_BTN,
        scancodes=[ecodes.BTN_0],
    ))
    server.register(Light(
        device={'r': led_r, 'g': led_g, 'b': led_b},
        name='light',
        topic=SUBTOPIC_LIGHT,
    ))
    server.start()

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    finally:
        loop.run_until_complete(server.close())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
