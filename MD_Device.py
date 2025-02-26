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
import time
from importlib import import_module

if MD_standalone:
    from MD_Globals import *
    from MD_Commands import MD_Commands
    from MD_Command import MD_Command
else:
    from .MD_Globals import *
    from .MD_Commands import MD_Commands
    from .MD_Command import MD_Command


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

    def __init__(self, device_id, device_name, **kwargs):
        '''
        This initializes the class object.

        As additional device classes are expected to be implemented as subclasses,
        most initialization steps are modularized as methods which can be overloaded
        as needed.
        As all pre-implemented methods are called in hopefully-logical sequence,
        this __init__ probably doesn't need to be changed.
        '''
        # get MultiDevice.device logger (if not already defined by derived class calling us via super().__init__())
        if not hasattr(self, 'logger'):
            self.logger = logging.getLogger('.'.join(__name__.split('.')[:-1]) + f'.{device_name}')

        self.logger.debug(f'device {device_name} initializing from {self.__class__.__name__} with arguments {kwargs}')

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
        self._initial_values_read = False
        self._cyclic_update_active = False
        self._plugin = self._plugin_params.get('plugin', None)

        self._data_received_callback = None
        self._commands_read = {}
        self._commands_initial = []
        self._commands_cyclic = {}

        self._command_class = kwargs.get('command_class', None)
        if self._command_class is None:
            self._command_class = MD_Command

        # set device parameters, if any
        self._set_device_params()

        # try to read configuration files
        if not self._read_configuration():
            self.logger.error('configuration could not be read, device disabled')
            return

        # instantiate connection object
        self._connection = self._get_connection()
        if not self._connection:
            self.logger.error(f'could not setup connection with {kwargs}, device disabled')
            return

        # the following code should only be run if not called from subclass via super()
        if self.__class__ is MD_Device:
            self.logger.debug(f'device initialized from {self.__class__.__name__}')

    def start(self):
        if self.alive:
            return
        if self._runtime_data_set:
            self.logger.debug('start method called')
        else:
            self.logger.error('start method called, but runtime data not set, device disabled')
            return

        self.alive = True
        self._connection.open()

        if self._connection.connected:
            self._read_initial_values()
            if not MD_standalone:
                self._create_cyclic_scheduler()

    def stop(self):
        self.logger.debug('stop method called')
        self.alive = False
        if self._plugin and self._plugin.scheduler_get(self.device + '_cyclic'):
            self._plugin.scheduler_remove(self.device + '_cyclic')
        self._connection.close()

    # def run_standalone(self):
    #     '''
    #     If you want to provide a standalone function, you'll have to implement
    #     this function with the appropriate code. You can use all functions from
    #     the MultiDevice class, the devices, connections and commands.
    #     You do not have an sh object, items or web interfaces.
    #
    #     As the base class should not have this method, it is commented out.
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
            self.logger.warning(f'trying to send command {command} with value {value}, but device is not active.')
            return False

        if not self._connection:
            self.logger.warning(f'trying to send command {command} with value {value}, but connection is None. This shouldn\'t happen...')
            return False

        if not self._connection.connected:
            self._connection.open()
            if not self._connection.connected:
                self.logger.warning(f'trying to send command {command} with value {value}, but connection could not be established.')
                return False

        try:
            data_dict = self._commands.get_send_data(command, value)
        except Exception as e:
            self.logger.warning(f'command {command} with value {value} produced error {e} on converting value, aborting')
            return False

        if data_dict['payload'] is None or data_dict['payload'] == '':
            self.logger.warning(f'command {command} with value {value} yielded empty command payload, aborting')
            return False

        data_dict = self._transform_send_data(data_dict)
        self.logger.debug(f'command {command} with value {value} yielded send data_dict {data_dict}')

        # if an error occurs on sending, an exception is thrown
        try:
            result = self._connection.send(data_dict)
        except Exception as e:
            self.logger.debug(f'error on sending command {command}, error was {e}')
            return False

        if result:
            self.logger.debug(f'command {command} received result {result}')
            try:
                value = self._commands.get_shng_data(command, result)
            except Exception as e:
                self.logger.info(f'command {command} received result {result}, error {e} occurred while converting. Discarding result.')
            else:            
                self.logger.debug(f'command {command} received result {result}, converted to value {value}')
                if self._data_received_callback:
                    self._data_received_callback(self.device, command, value)
                else:
                    self.logger.warning(f'command {command} received result {result}, but _data_received_callback is not set. Discarding result.')
        return True

    def on_data_received(self, command, data):
        '''
        Callback function for received data e.g. from an event loop
        Processes data and dispatches value to plugin class

        :param command: the command in reply to which data was received
        :param data: received data in 'raw' connection format
        :type command: str
        '''
        if command is not None:
            self.logger.debug(f'received data "{data}" for command {command}')
        else:
            # command == None means that we got raw data from a callback and don't know yet to
            # which command this belongs to. So find out...
            self.logger.debug(f'received data "{data}" without command specification')
            command = self._commands.get_command_from_reply(data)
            if not command:
                self.logger.debug(f'data "{data}" did not identify a known command, ignoring it')
                return

        try:
            value = self._commands.get_shng_data(command, data)
        except Exception as e:
            self.logger.info(f'received data "{data}" for command {command}, error {e} occurred while converting. Discarding data.')
        else:
            self.logger.debug(f'received data "{data}" for command {command} converted to value {value}')
            if self._data_received_callback:
                self._data_received_callback(self.device, command, value)
            else:
                self.logger.warning(f'command {command} yielded value {value}, but _data_received_callback is not set. Discarding data.')

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
            self.logger.error(f'error in runtime data: {e}. Stopping device.')

    def update_device_params(self, **kwargs):
        '''
        Updates configuration parametes for device. Needs device to not be running

        overload as needed.
        '''
        if self.alive:
            self.logger.warning(f'tried to update params with {kwargs}, but device is still running. Ignoring request')
            return

        if not kwargs:
            self.logger.warning('update_device_params called without new parameters. Don\'t know what to update.')
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

    def _transform_send_data(self, data_dict):
        '''
        This method provides a way to adjust, modify or transform all data before
        it is sent to the device.
        This might be to add general parameters, add/change line endings or
        add your favourite pets' name... 
        By default, nothing happens here.
        '''
        return data_dict

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

        conn_class = 'MD_Connection_' + '_'.join([tok.capitalize() for tok in conn_type.split('_')])
        self.logger.debug(f'wanting connection class named {conn_class}')

        mod_str = 'MD_Connection'
        if not MD_standalone:
            mod_str = '.'.join(self.__module__.split('.')[:-2]) + '.' + mod_str

        module = import_module(mod_str)
        if hasattr(module, conn_class):
            cls = getattr(module, conn_class)
        else:
            cls = getattr(module, 'MD_Connection')

        self.logger.debug(f'using connection class {cls}')
        return cls(self.device_id, self.device, self.on_data_received, **self._plugin_params)

    #
    #
    # utility methods
    #
    #

    def _create_cyclic_scheduler(self):
        '''
        Setup the scheduler to handle cyclic read commands and find the proper time for the cycle.
        '''
        if not self.alive:
            return

        # did we get the plugin instance?
        if not self._plugin:
            return

        # find shortest cycle
        shortestcycle = -1
        for cmd in self._commands_cyclic:
            cycle = self._commands_cyclic[cmd]['cycle']
            if shortestcycle == -1 or cycle < shortestcycle:
                shortestcycle = cycle

        # Start the worker thread
        if shortestcycle != -1:

            # Balance unnecessary calls and precision
            workercycle = int(shortestcycle / 2)

            # just in case it already exists...
            if self._plugin.scheduler_get(self.device + '_cyclic'):
                self._plugin.scheduler_remove(self.device + '_cyclic')
            self._plugin.scheduler_add(self.device + '_cyclic', self._read_cyclic_values, cycle=workercycle, prio=5, offset=0)
            self.logger.info(f'Added cyclic worker thread {self.device}_cyclic with {workercycle} s cycle. Shortest item update cycle found was {shortestcycle} s')

    def _read_initial_values(self):
        '''
        Read all values configured to be read at startup
        '''
        if self._commands_initial and self._commands_initial != [] and not self._initial_values_read:
            self.logger.info('Starting initial read commands')
            for cmd in self._commands_initial:
                self.logger.debug(f'Sending initial command {cmd}')
                self.send_command(cmd)
            self._initial_values_read = True
            self.logger.info('Initial read commands sent')
        elif self._initial_values_read:
            self.logger.debug('_read_initial_values() called, but inital values were already read. Ignoring')

    def _read_cyclic_values(self):
        '''
        Recall function for cyclic scheduler. Reads all values configured to be read cyclically.
        '''
        # check if another cyclic cmd run is still active
        if self._cyclic_update_active:
            self.logger.warning('Triggered cyclic command read, but previous cyclic run is still active. Check device and cyclic configuration (too much/too short?)')
            return
        else:
            self.logger.info('Triggering cyclic command read')
 
        # set lock
        self._cyclic_update_active = True
        currenttime = time.time()
        read_cmds = 0
        todo = []
        for cmd in self._commands_cyclic:
 
            # Is the command already due?
            if self._commands_cyclic[cmd]['next'] <= currenttime:
                todo.append(cmd)
 
        for cmd in todo:
            # as this loop can take considerable time, repeatedly check if shng wants to stop
            if not self.alive:
                self.logger.info('Stop command issued, cancelling cyclic read')
                return

            # also leave early on disconnect
            if not self._connection.connected:
                self.logger.info('Disconnect detected, cancelling cyclic read')
                return

            self.logger.debug(f'Triggering cyclic read of command {cmd}')
            self.send_command(cmd)
            self._commands_cyclic[cmd]['next'] = currenttime + self._commands_cyclic[cmd]['cycle']
            read_cmds += 1
 
        self._cyclic_update_active = False
        if read_cmds:
            self.logger.debug(f'Cyclic command read took {(time.time() - currenttime):.1f} seconds for {read_cmds} items')

    def _read_configuration(self):
        '''
        This initiates reading of configuration.
        Basically, this calls the MD_Commands object to fill itselt; but if needed,
        this can be overloaded to do something else.
        '''
        cls = self._command_class
        if cls is None:
            cls = MD_Command
        self._commands = MD_Commands(self.device_id, self.device, cls, **self._plugin_params)
        return True


