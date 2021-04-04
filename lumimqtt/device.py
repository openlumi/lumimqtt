"""
Basic Device class
"""


class Device:
    MQTT_VALUES = None

    def __init__(self, device, name, topic):
        self.name = name
        self.device = device
        self.topic = topic
