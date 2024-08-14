#!/usr/bin/env python

from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name='lumimqtt',
    use_scm_version={
        'write_to': 'lumimqtt/__version__.py',
    },
    setup_requires=['setuptools_scm'],
    description='Xiaomi Lumi Gateway MQTT integration',
    long_description=long_description,
    long_description_content_type="text/markdown",
    author='Ivan Belokobylskiy',
    author_email='belokobylskij@gmail.com',
    url='https://github.com/openlumi/lumimqtt/',
    install_requires=[
        'evdev>=1.0.0',
        'aio-mqtt-mod>=0.3.2',
    ],
    packages=['lumimqtt'],
    entry_points={
        'console_scripts': ['lumimqtt=lumimqtt.__main__:main'],
    },
    classifiers=[
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Utilities',
    ],
)
