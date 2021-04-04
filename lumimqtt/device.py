"""
Basic Device class
"""


class Device:
    MQTT_VALUES = None

    def __init__(self, name, device_file, topic):
        self.name = name
        self.device_file = device_file
        self.topic = topic
