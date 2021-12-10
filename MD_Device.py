#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2020-      Sebastian Helms             Morg @ knx-user-forum
#########################################################################
#  This file aims to become part of SmartHomeNG.
#  https://www.smarthomeNG.de
#  https://knx-user-forum.de/forum/supportforen/smarthome-py
#
#  MD_Device for MultiDevice plugin
#
#  SmartHomeNG is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHomeNG is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHomeNG. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################

import logging

from .MD_Globals import *
from .MD_Command import MD_Command
from .MD_Commands import MD_Commands
from .MD_Connection import (MD_Connection, MD_Connection_Net_TCP_Request, MD_Connection_Net_TCP_Reply,
                            MD_Connection_Net_TCP_Server, MD_Connection_Net_UDP_Server,
                            MD_Connection_Serial_Async, MD_Connection_Serial_Client)


#############################################################################################################################################################################################################################################
#
# class MD_Device
#
#############################################################################################################################################################################################################################################

class MD_Device(object):
    '''
    This class is the base class for a simple device class. It can process commands
    by sending values to the device and collect data by parsing data received from
    the device.

    Configuration is done via dev_<device_id>/ commands.py (see there for format)

    :param device_id: device type as used in derived class names
    :param device_name: device name for use in item configuration and logs
    :type device_id: str
    :type device_name: str
    '''

    def __init__(self, device_id, device_name, standalone=False, **kwargs):
        '''
        This initializes the class object.

        As additional device classes are expected to be implemented as subclasses,
        most initialization steps are modularized as methods which can be overloaded
        as needed.
        As all pre-implemented methods are called in hopefully-logical sequence,
        this __init__ probably doesn't need to be changed.
        '''
        # get MultiDevice logger (if not already defined by subclass)
        # NOTE: later on, decide if every device logs to its own logger?
        if not hasattr(self, 'logger'):
            self.logger = logging.getLogger(__name__)

        self.logger.debug(f'Device {device_name}: device initializing from {self.__class__.__name__} with arguments {kwargs}')

        # the connection object
        self._connection = None

        # the commands object
        self._commands = None

        # set class properties
        self._plugin_params = kwargs
        self.device_id = device_id
        self.device = device_name
        self.alive = False
        self._runtime_data_set = False

        self._data_received_callback = None
        self._commands_read = {}
        self._commands_initial = []
        self._commands_cyclic = {}

        self._standalone = standalone

        # set device parameters, if any
        self._set_device_params()

        # try to read configuration files
        if not self._read_configuration():
            self.logger.error(f'Device {self.device}: configuration could not be read, device disabled')
            return

        # instantiate connection object
        self._connection = self._get_connection()
        if not self._connection:
            self.logger.error(f'Device {self.device}: could not setup connection with {kwargs}, device disabled')
            return

        # the following code should only be run if not called from subclass via super()
        if self.__class__ is MD_Device:
            self.logger.debug(f'Device {self.device}: device initialized from {self.__class__.__name__}')

    def start(self):
        if self.alive:
            return
        if self._runtime_data_set:
            self.logger.debug(f'Device {self.device}: start method called')
        else:
            self.logger.error(f'Device {self.device}: start method called, but runtime data not set, device disabled')
            return

        self.alive = True
        self._connection.open()

    def stop(self):
        self.logger.debug(f'Device {self.device}: stop method called')
        self.alive = False
        self._connection.close()

    # def run_standalone(self):
    #     '''
    #     If you want to provide a standalone function, you'll have to implement
    #     this function with the appropriate code. You can use all functions from
    #     the MultiDevice class, the devices, connections and commands.
    #     You do not have an sh object, items or web interfaces.
    #
    #     As this should not be present for the base class, the definition is
    #     commented out.
    #     '''
    #     pass

    def send_command(self, command, value=None):
        '''
        Sends the specified command to the device providing <value> as data

        :param command: the command to send
        :param value: the data to send, if applicable
        :type command: str
        :return: True if send was successful, False otherwise
        :rtype: bool
        '''
        if not self.alive:
            self.logger.warning(f'Device {self.device}: trying to send command {command} with value {value}, but device is not active.')
            return False

        if not self._connection:
            self.logger.warning(f'Device {self.device}: trying to send command {command} with value {value}, but connection is None. This shouldn\'t happen...')

        if not self._connection.connected:
            self._connection.open()
            if not self._connection.connected:
                self.logger.warning(f'Device {self.device}: trying to send command {command} with value {value}, but connection could not be established.')
                return False

        data_dict = self._commands.get_send_data(command, value)
        self.logger.debug(f'Device {self.device}: command {command} with value {value} yielded send data_dict {data_dict}')

        # if an error occurs on sending, an exception is thrown
        try:
            result = self._connection.send(data_dict)
        except Exception as e:
            self.logger.debug(f'Device {self.device}: error on sending command {command}, error was {e}')
            return False

        if result:
            self.logger.debug(f'Device {self.device}: command {command} received result of {result}')
            value = self._commands.get_shng_data(command, result)
            self.logger.debug(f'Device {self.device}: command {command} received result {result}, converted to value {value}')
            if self._data_received_callback:
                self._data_received_callback(self.device, command, value)
            else:
                self.logger.warning(f'Device {self.device}: received data {value} for command {command}, but _data_received_callback is not set. Discarding data.')
        return True

    def data_received(self, command, data):
        '''
        Callback function for received data e.g. from an event loop
        Processes data and dispatches value to plugin class

        :param command: the command in reply to which data was received
        :param data: received data in 'raw' connection format
        :type command: str
        '''
        self.logger.debug(f'Device {self.device}: data received for command {command}: {data}')
        value = self._commands.get_shng_data(command, data)
        self.logger.debug(f'Device {self.device}: data received for command {command}: {data} converted to value {value}')
        if self._data_received_callback:
            self._data_received_callback(command, value)
        else:
            self.logger.warning(f'Device {self.device}: received data {value} for command {command}, but _data_received_callback is not set. Discarding data.')

    def read_all_commands(self):
        '''
        Triggers all configured read commands
        '''
        for cmd in self._commands_read:
            self.send_command(cmd)

    def is_valid_command(self, command, read=None):
        '''
        Validate if 'command' is a valid command for this device
        Possible to check only for reading or writing

        :param command: the command to test
        :type command: str
        :param read: check for read (True) or write (False), or both (None)
        :type read: bool | NoneType
        :return: True if command is valid, False otherwise
        :rtype: bool
        '''
        if self._commands:
            return self._commands.is_valid_command(command, read)
        else:
            return False

    def set_runtime_data(self, **kwargs):
        '''
        Sets runtime data received from the plugin class
        '''
        try:
            self._commands_read = kwargs['read_commands']
            self._commands_cyclic = kwargs['cycle_commands']
            self._commands_initial = kwargs['initial_commands']
            self._data_received_callback = kwargs['callback']
            self._runtime_data_set = True
        except KeyError as e:
            self.logger.error(f'Device {self.device}: error in runtime data: {e}. Stopping device.')

    def update_device_params(self, **kwargs):
        '''
        Updates configuration parametes for device. Needs device to not be running

        overload as needed.
        '''
        if self.alive:
            self.logger.warning(f'Device {self.device}: tried to update params with {kwargs}, but device is still running. Ignoring request')
            return

        if not kwargs:
            self.logger.warning(f'Device {self.device}: update_device_params called without new parameters. Don\'t know what to update.')
            return

        # merge new params with self._plugin_params, overwrite old values if necessary
        self._plugin_params = {**self._plugin_params, **kwargs}

        # update this class' settings
        self._set_device_params()

        # update = recreate the connection with new parameters
        self._connection = self._get_connection()

    #
    #
    # check if overloading needed
    #
    #

    def _set_device_params(self, **kwargs):
        '''
        This method parses self._parameters for parameters it needs itself and does the
        necessary initialization.
        Needs to be overloaded for maximum effect
        '''
        pass

    def _get_connection(self):
        '''
        return connection object. Try to identify the wanted connection  and return
        the proper subclass instead. If no decision is possible, just return an
        instance of MD_Connection.

        If you need to use other connection types for your device, implement it
        and preselect with PLUGIN_ARG_CONNECTION in /etc/plugin.yaml, so this
        class will never be used.
        Otherwise, just parse them in after calling super()._set_connection_params()

        HINT: If you need to modify this, just write something new.
        The "autodetect"-code will probably only be used with unaltered connection
        classes. Just return the wanted connection object and ride into the light.
        '''
        conn_type = None
        params = self._plugin_params

        # try to find out what kind of connection is wanted
        if PLUGIN_ARG_CONNECTION in self._plugin_params and self._plugin_params[PLUGIN_ARG_CONNECTION] in CONNECTION_TYPES:
            conn_type = self._plugin_params[PLUGIN_ARG_CONNECTION]
        else:

            if PLUGIN_ARG_NET_PORT in self._plugin_params:

                # no further information on network specifics, use basic HTTP TCP client
                conn_type = CONN_NET_TCP_REQ

            elif PLUGIN_ARG_SERIAL_PORT in self._plugin_params:

                # this seems to be a serial killer application
                conn_type = CONN_SER_CLI

            if conn_type:
                params[PLUGIN_ARG_CONNECTION] = conn_type

        if conn_type == CONN_NET_TCP_REQ:

            return MD_Connection_Net_TCP_Request(self.device_id, self.device, self._data_received_callback, **self._plugin_params)
        elif conn_type == CONN_NET_TCP_SYN:

            return MD_Connection_Net_TCP_Reply(self.device_id, self.device, self._data_received_callback, **self._plugin_params)
        elif conn_type == CONN_NET_TCP_SRV:

            return MD_Connection_Net_TCP_Server(self.device_id, self.device, self._data_received_callback, **self._plugin_params)
        elif conn_type == CONN_NET_UDP_SRV:

            return MD_Connection_Net_UDP_Server(self.device_id, self.device, self._data_received_callback, **self._plugin_params)
        elif conn_type == CONN_SER_CLI:

            return MD_Connection_Serial_Client(self.device_id, self.device, self._data_received_callback, **self._plugin_params)
        elif conn_type == CONN_SER_ASYNC:

            return MD_Connection_Serial_Async(self.device_id, self.device, self._data_received_callback, **self._plugin_params)
        else:
            return MD_Connection(self.device_id, self.device, self._data_received_callback, **self._plugin_params)

        # Please go on. There is nothing to see here. You shouldn't be here anyway...
        self.logger.error(f'Device {self.device}: could not setup connection with {params}, device disabled')

    #
    #
    # private utility methods
    #
    #

    def _read_configuration(self):
        '''
        This initiates reading of configuration.
        Basically, this calls the MD_Commands object to fill itselt; but if needed,
        this can be overloaded to do something else.
        '''
        self._commands = MD_Commands(self.device_id, self.device, MD_Command, self._standalone, **self._plugin_params)
        return True


