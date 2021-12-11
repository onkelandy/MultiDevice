if MD_standalone:
    from MD_Device import MD_Device
    from MD_Commands import MD_Commands
    from MD_Command import MD_Command_Str
else:
    from ..MD_Device import MD_Device
    from ..MD_Commands import MD_Commands
    from ..MD_Command import MD_Command_Str

import logging


class MD_Device(MD_Device):

    def __init__(self, device_id, device_name, **kwargs):

        # get MultiDevice logger
# NOTE: later on, decide if every device logs to its own logger?
        s, __, __ = __name__.rpartition('.')
        s, __, __ = s.rpartition('.')
        self.logger = logging.getLogger(s)

        super().__init__(device_id, device_name, **kwargs)

        # TODO - remove when done. say hello
        self.logger.debug(f'Device {device_name}: device initialized from {__spec__.name} with arguments {kwargs}')
