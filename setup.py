#!/usr/bin/env python

from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name='lumimqtt',
    version='1.0.4',
    description='Xiaomi Lumi Gateway MQTT integration',
    long_description=long_description,
    long_description_content_type="text/markdown",
    author='Ivan Belokobylskiy',
    author_email='belokobylskij@gmail.com',
    url='https://github.com/openlumi/lumimqtt/',
    scripts=['lumimqtt'],
    py_modules=['lumimqtt'],
    install_requires=[
        'evdev>=1.0.0',
        'aio-mqtt>=0.2.0',
    ],
    classifiers=[
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Utilities',
    ],
)
