#!/usr/bin/env python

from setuptools import setup

from lumimqtt.__version__ import VERSION

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name='lumimqtt',
    version=VERSION,
    description='Xiaomi Lumi Gateway MQTT integration',
    long_description=long_description,
    long_description_content_type="text/markdown",
    author='Ivan Belokobylskiy',
    author_email='belokobylskij@gmail.com',
    url='https://github.com/openlumi/lumimqtt/',
    install_requires=[
        'evdev>=1.0.0',
        'aio-mqtt>=0.2.0',
    ],
    packages=['lumimqtt'],
    entry_points={
        'console_scripts': ['lumimqtt=lumimqtt.__main__:main'],
    },
    classifiers=[
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Utilities',
    ],
)
