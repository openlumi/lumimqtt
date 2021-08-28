"""
LUMI light control
"""
import asyncio as aio
import contextlib
import logging
import subprocess
import sys
from collections import defaultdict

from .device import Device

logger = logging.getLogger(__name__)


class Command(Device):
    """
    Custom command control
    """

    def __init__(self, name, device_file, topic):
        super().__init__(name, device_file, topic)
        self.command = device_file

    @property
    def topic_set(self):
        return f'{self.topic}/set'

    @contextlib.contextmanager
    def fix_watcher(self):
        if sys.version_info < (3, 8, 0):
            # https://github.com/aio-libs/aiohttp/pull/2075/files#diff-70599d14cae2351e35e46867bce26e325e84f3b84ce218718239c4bfeac4dcf5R445-R448
            loop = aio.get_event_loop()
            policy = aio.get_event_loop_policy()
            watcher = policy.get_child_watcher()
            watcher.attach_loop(loop)
        yield

    @staticmethod
    def quote(s):
        try:
            return str(s).replace('"', '\\"').replace("'", "\\'").replace('$', '')
        except:
            return ""

    async def run_command(self, value):
        if isinstance(value, dict):
            value = {
                k: self.quote(v)
                for k, v in value.items()
            }
            command = self.command.format_map(defaultdict(str, **value))
        else:
            command = self.command.format_map(defaultdict(str, text=value))

        with self.fix_watcher():
            proc = await aio.create_subprocess_shell(
                command,
                loop=aio.get_event_loop(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        await proc.wait()

    async def set(self, value):
        logger.info(f'{self.name}: run command with params: {value}')
        await self.run_command(value)
