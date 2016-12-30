"""
Receive signals from a keyboard and use it as a remote control.

This component allows to use a keyboard as remote control. It will
fire ´keyboard_remote_command_received´ events witch can then be used
in automation rules.

The `evdev` package is used to interface with the keyboard and thus this
is Linux only. It also means you can't use your normal keyboard for this,
because `evdev` will block it.

Example:
  keyboard_remote:
    device_descriptor: '/dev/input/by-id/foo'
    type: 'key_up' # optional alternaive 'key_down' and 'key_hold'
    # be carefull, 'key_hold' fires a lot of events

  and an automation rule to bring breath live into it.

  automation:
    alias: Keyboard All light on
    trigger:
      platform: event
      event_type: keyboard_remote_command_received
      event_data:
        key_code: 107 # inspect log to obtain desired keycode
    action:
      service: light.turn_on
      entity_id: light.all
"""

# pylint: disable=import-error
import threading
import logging
import os
import time

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.const import (
    EVENT_HOMEASSISTANT_START,
    EVENT_HOMEASSISTANT_STOP
)

DOMAIN = "keyboard_remote"
REQUIREMENTS = ['evdev==0.6.1']
_LOGGER = logging.getLogger(__name__)
ICON = 'mdi:remote'
KEYBOARD_REMOTE_COMMAND_RECEIVED = 'keyboard_remote_command_received'
KEY_CODE = 'key_code'
KEY_VALUE = {'key_up': 0, 'key_down': 1, 'key_hold': 2}
TYPE = 'type'
DEVICE_DESCRIPTOR = 'device_descriptor'

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(DEVICE_DESCRIPTOR): cv.string,
        vol.Optional(TYPE, default='key_up'):
        vol.All(cv.string, vol.Any('key_up', 'key_down', 'key_hold')),
    }),
}, extra=vol.ALLOW_EXTRA)


def setup(hass, config):
    """Setup keyboard_remote."""
    config = config.get(DOMAIN)
    device_descriptor = config.get(DEVICE_DESCRIPTOR)
    if not device_descriptor or not os.path.exists(device_descriptor):
        id_folder = '/dev/input/by-id/'
        _LOGGER.error(
            'A device_descriptor must be defined. '
            'Possible descriptors are %s:\n%s',
            id_folder, os.listdir(id_folder)
        )
        return

    key_value = KEY_VALUE.get(config.get(TYPE, 'key_up'))

    keyboard_remote = KeyboardRemote(
        hass,
        device_descriptor,
        key_value
    )

    def _start_keyboard_remote(_event):
        keyboard_remote.run()

    def _stop_keyboard_remote(_event):
        keyboard_remote.stopped.set()

    hass.bus.listen_once(
        EVENT_HOMEASSISTANT_START,
        _start_keyboard_remote
    )
    hass.bus.listen_once(
        EVENT_HOMEASSISTANT_STOP,
        _stop_keyboard_remote
    )

    return True


class KeyboardRemote(threading.Thread):
    """This interfaces with the inputdevice using evdev."""

    def __init__(self, hass, device_descriptor, key_value):
        """Construct a KeyboardRemote interface object."""
        from evdev import InputDevice

        self.dev = InputDevice(device_descriptor)
        threading.Thread.__init__(self)
        self.stopped = threading.Event()
        self.hass = hass
        self.key_value = key_value
        self.device_descriptor = device_descriptor

    def run(self):
        """Main loop of the KeyboardRemote."""
        from evdev import categorize, ecodes, InputDevice
        _LOGGER.debug('KeyboardRemote interface started for %s', self.dev)

        self.dev.grab()
        keyboard_connected = True

        while not self.stopped.isSet():

            # Is keyboard still there?
            keyboard_still_connected = os.path.exists(self.device_descriptor)

            # still disconnected
            if not keyboard_connected and not keyboard_still_connected:
                continue

            # keyboard reconnected
            if not keyboard_connected and keyboard_still_connected:
                _LOGGER.debug('KeyboardRemote: keyboard re-connected, %s',
                              self.device_descriptor)
                time.sleep(1)  # Time to allow ACL permissions to kick in
                self.dev = InputDevice(self.device_descriptor)
                self.dev.grab()
                keyboard_connected = True

            try:
                event = self.dev.read_one()
            except IOError:  # Keyboard Disconnected
                keyboard_connected = False
                _LOGGER.debug(
                    'KeyboardRemote: keyboard disconnected, %s',
                    self.device_descriptor)
                continue

            if not event:
                continue

            # pylint: disable=no-member
            if event.type is ecodes.EV_KEY and event.value is self.key_value:
                _LOGGER.debug(categorize(event))
                self.hass.bus.fire(
                    KEYBOARD_REMOTE_COMMAND_RECEIVED,
                    {KEY_CODE: event.code}
                )
