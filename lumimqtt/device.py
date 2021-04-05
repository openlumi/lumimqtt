"""
Basic Device class
"""
import os


class Device:
    MQTT_VALUES = None

    def __init__(self, name, device_file, topic=None):
        self.name = name
        self.device_file = device_file
        self.topic = topic

    def read_raw(self, device_file=None):
        if not device_file:
            device_file = self.device_file
        if os.path.exists(device_file):
            with open(device_file, 'r') as f:
                return f.read().strip()
        return None
