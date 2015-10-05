from __future__ import print_function

import threading
import logging
from collections import defaultdict
from binascii import hexlify

from . import exceptions

log = logging.getLogger(__name__)


class BLEDevice(object):
    """
    Interface for a Bluetooth Low Energy device that can use either the Bluegiga
    BGAPI (cross platform) or GATTTOOL (Linux only) as the backend.
    """
    def __init__(self, address):
        """
        Initialize.

        address -- a string containing the mac address of the BLE device in
                       the following format: "XX:XX:XX:XX:XX:XX"
        backend -- an instantiated instance of a BLEBacked.

        Example:

            dongle = pygatt.backends.BGAPIBackend('/dev/ttyAMC0')
            my_ble_device = pygatt.classes.BLEDevice(
                '01:23:45:67:89:ab', bgapi=dongle)
        """
        self._characteristics = {}
        self._address = address
        self._callbacks = defaultdict(set)
        self._subscribed_handlers = {}
        self._lock = threading.Lock()

    def bond(self):
        """
        Create a new bond or use an existing bond with the device and make the
        current connection bonded and encrypted.
        """
        raise NotImplementedError()

    def get_rssi(self):
        """
        Get the receiver signal strength indicator (RSSI) value from the BLE
        device.

        Returns the RSSI value in dBm on success.
        Returns None on failure.
        """
        raise NotImplementedError()

    def char_read(self, uuid):
        """
        Reads a Characteristic by UUID.

        uuid -- UUID of Characteristic to read as a string.

        Returns a bytearray containing the characteristic value on success.
        Returns None on failure.

        Example:
            my_ble_device.char_read('a1e8f5b1-696b-4e4c-87c6-69dfe0b0093b')
        """
        raise NotImplementedError()

    def char_write(self, uuid, value, wait_for_response=False):
        """
        Writes a value to a given characteristic handle.

        uuid -- the UUID of the characteristic to write to.
        value -- the value as a bytearray to write to the characteristic.
        wait_for_response -- wait for response after writing (GATTTOOL only).

        Example:
            my_ble_device.char_write('a1e8f5b1-696b-4e4c-87c6-69dfe0b0093b',
                                     bytearray([0x00, 0xFF]))
        """
        return self.char_write_handle(self.get_handle(uuid), value,
                                      wait_for_response=wait_for_response)

    def char_write_handle(self, handle, value, wait_for_response=False):
        raise NotImplementedError()

    def disconnect(self):
        raise NotImplementedError()

    def subscribe(self, uuid, callback=None, indication=False):
        """
        Enables subscription to a Characteristic with ability to call callback.

        uuid -- UUID as a string of the characteristic to subscribe.
        callback -- function to be called when a notification/indication is
                    received on this characteristic.
        indication -- use indications (requires application ACK) rather than
                      notifications (does not requrie application ACK).
        """
        log.info(
            'Subscribing to uuid=%s with callback=%s and indication=%s',
            uuid, callback, indication)
        # Expect notifications on the value handle...
        value_handle = self.get_handle(uuid)

        # but write to the characteristic config to enable notifications
        # TODO with the BGAPI backend we can be smarter and fetch the actual
        # characteristic config handle - we can also do that with gattool if we
        # use the 'desc' command, so we'll need to change the "get_handle" API
        # to be able to get the value or characteristic config handle.
        characteristic_config_handle = value_handle + 1

        properties = bytearray([
            0x2 if indication else 0x1,
            0x0
        ])

        with self._lock:
            if callback is not None:
                self._callbacks[value_handle].add(callback)

            if self._subscribed_handlers.get(value_handle, None) != properties:
                self.char_write_handle(
                    characteristic_config_handle,
                    properties,
                    wait_for_response=False
                )
                log.debug("Subscribed to uuid=%s", uuid)
                self._subscribed_handlers[value_handle] = properties
            else:
                log.debug("Already subscribed to uuid=%s", uuid)

    def get_handle(self, uuid):
        """
        Look up and return the handle for an attribute by its UUID.
        :param uuid: The UUID of the characteristic.
        :type uuid: str
        :return: None if the UUID was not found.
        """
        log.debug("Looking up handle for characteristic %s", uuid)
        if uuid not in self._characteristics:
            self._characteristics = self.discover_characteristics()

        characteristic = self._characteristics.get(uuid)
        if characteristic is None:
            message = "No characteristic found matching %s" % uuid
            log.warn(message)
            raise exceptions.BLEError(message)

        # TODO support filtering by descriptor UUID, or maybe return the whole
        # Characteristic object
        log.debug("Found %s" % characteristic)
        return characteristic.handle

    def receive_notification(self, handle, value):
        """
        Receive a notification from the connected device and propagate the value
        to all registered callbacks.
        """

        log.info('Received notification on handle=0x%x, value=0x%s',
                 handle, hexlify(value))
        with self._lock:
            if handle in self._callbacks:
                for callback in self._callbacks[handle]:
                    callback(handle, value)
