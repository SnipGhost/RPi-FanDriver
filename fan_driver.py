#!/usr/bin/python3
# -*- coding: utf-8 -*-
import RPi.GPIO as GPIO
import sys
import json
import logging
import signal
import threading
from time import sleep
from logging.handlers import WatchedFileHandler


class FanDriverDaemon():
    def __init__(self, config_file, logger=None):
        self.config_file = config_file
        self.config = self._load_config(config_file)

        logging.basicConfig(format=self.config['log_format'])
        if logger:
            self.log = logger
        else:
            self.log = logging.getLogger()

        if self.config['log_file']:
            fh = WatchedFileHandler(self.config['log_file'])
            formatter = logging.Formatter(self.config['log_format'])
            fh.setFormatter(formatter)
            self.log.addHandler(fh)
        self.log.setLevel(getattr(logging, self.config['log_level']))
        self.log.info('Loaded config')
        self.log.debug('Config: %s', self.config)

        self.end_event = threading.Event()
        self.reload_event = threading.Event()
        self.__setup_signal_handlers()

        self.pin_state = False
        self._setup_pins()
        self.log.info('FanDriverDaemon inited')

    def _load_config(self, config_file):
        # default log format
        log_format = [
            "[PID: %(process)d]",
            "%(asctime)s",
            "[%(levelname)s]",
            "%(module)s:%(funcName)s:%(lineno)d",
            "%(message)s",
        ]
        # default config
        config = {
            'log_level': 'INFO',   # logging level
            'log_file': None,      # logging file (None for stderr)
            'log_format': None,    # logging format (None for default)
            'temp_max': 55,        # temperature that activate fan
            'temp_min': 45,        # temperature that deactivate fan
            'sleep': 1,            # time to sleep in seconds
            'control_pin': 21,     # transistor base controller pin
        }
        with open(config_file) as file:
            data = json.load(file)
            config.update(data)
        if not config['log_format']:
            config['log_format'] = ' '.join(log_format)
        return config

    def _reload_config(self, config_file):
        self.config = self._load_config(config_file)
        self.log.info('Reloaded config')
        self.log.debug('Config: %s', self.config)
        self._cleanup_pins()
        self._setup_pins()

    def __signal_stop_handler(self, signum, frame):
        # no time-consuming actions here!
        # just also sys.stderr.write is a bad idea
        self.running = False  # stop endless loop
        self.end_event.set()  # wake from sleep

    def __signal_reload_handler(self, signum, frame):
        # no time-consuming actions here!
        # just also sys.stderr.write is a bad idea
        self.reload_event.set()

    def __setup_signal_handlers(self):
        signal.signal(signal.SIGTERM, self.__signal_stop_handler)
        signal.signal(signal.SIGINT, self.__signal_stop_handler)
        signal.signal(signal.SIGHUP, self.__signal_reload_handler)

    def _get_temp(self, temp_file='/sys/class/thermal/thermal_zone0/temp'):
        with open(temp_file) as file:
            temp = float(file.read()) / 1000
        return temp

    def _setup_pins(self):
        # numerate as BCM
        GPIO.setmode(GPIO.BCM)
        init_state = GPIO.HIGH if self.pin_state else GPIO.LOW
        GPIO.setup(self.config['control_pin'], GPIO.OUT, initial=init_state)

    def _cleanup_pins(self):
        GPIO.cleanup()

    def work(self):
        pin = self.config['control_pin']
        temp = self._get_temp()
        self.log.debug('Temp: %d°C', temp)
        if (temp > self.config['temp_max'] and not self.pin_state) or \
                (temp < self.config['temp_min'] and self.pin_state):
            self.pin_state = not self.pin_state
            GPIO.output(pin, self.pin_state)
            self.log.info('Changed pin#%d to %s', pin, self.pin_state)

    def run(self):
        self.log.info('FanDriverDaemon.run: starting fan driver')
        try:
            self.running = True
            while self.running:
                self.work()
                # sleep until timeout or end_event set
                # look for self.__signal_stop_handler
                self.end_event.wait(timeout=self.config['sleep'])
                # and just catch reload after all work on iteration
                if self.reload_event.is_set():
                    self._reload_config(self.config_file)
                    self.reload_event.clear()
        except BaseException:
            exception = sys.exc_info()
            error_tpl = 'FanDriverDaemon.run: unexpected error {0} {1} {2}'
            self.log.error(error_tpl.format(*exception), exc_info=True)
        finally:
            self._cleanup_pins()
            self.log.info('FanDriverDaemon.run: shutting down')


if __name__ == "__main__":
    conf = sys.argv[1] if len(sys.argv) > 1 else '/etc/fan_driver.config.json'
    driver = FanDriverDaemon(conf)
    driver.run()
