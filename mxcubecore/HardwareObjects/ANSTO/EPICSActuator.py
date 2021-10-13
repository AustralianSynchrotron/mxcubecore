#! /usr/bin/env python
# encoding: utf-8

"""
Superclass for EPICS actuators

Should be put as the first superclass,
e.g. class MotorMockup(EPICSActuator, AbstractMotor):
"""

import time
import random
import gevent
from mxcubecore.HardwareObjects.abstract import AbstractActuator
import logging

# __copyright__ = """ Copyright © 2010-2020 by the MXCuBE collaboration """
__license__ = "LGPLv3+"


class EPICSActuator(AbstractActuator.AbstractActuator):
    """EPCIS actuator"""

    def __init__(self, name):
        super(EPICSActuator, self).__init__(name)
        self.__move_task = None
        self._nominal_limits = (-1E4, 1E4)

    def init(self):
        """ Initialisation method """
        super(EPICSActuator, self).init()
        self.update_state(self.STATES.READY)

    def _move(self, value):
        """ Simulated value change - override as needed

        Must set specific_state as needed, take a non-zero amount of time
        call update_value for intermediate positions
        and return the final value (in case it does not match the input value)

        Args:
            value : target actuator value

        Returns:
            final actuator value (may differ from target value)
        """
        pass

    def get_value(self):
        """Read the actuator position.
        Returns:
            float: Actuator position.
        """
        pass

    def set_value(self, value, timeout=0):
        """
        Set actuator to absolute value.
        This is NOT the recommended way, but for technical reasons
        overriding is necessary in this particular case
        Args:
            value (float): target value
            timeout (float): optional - timeout [s],
                             If timeout == 0: return at once and do not wait (default);
                             if timeout is None: wait forever.
        Raises:
            ValueError: Value not valid or attemp to set read-only actuator.
        """
        if self.read_only:
            raise ValueError("Attempt to set value for read-only Actuator")
        if self.validate_value(value):
            self.update_state(self.STATES.BUSY)
            if timeout or timeout is None:
                with gevent.Timeout(
                    timeout, RuntimeError("Motor %s timed out" % self.username)
                ):
                    self._set_value(value)
                    new_value = self._move(value)
            else:
                self._set_value(value)
                self.__move_task = gevent.spawn(self._move, value)
        else:
            logging.getLogger("user_level_log").error(
                f"{self.username} is out of limits."
                f" Limits are {self.get_limits()}")

            raise ValueError("Invalid value %s; limits are %s" %
                             (value, self.get_limits()))

    def abort(self):
        """Imediately halt movement. By default self.stop = self.abort"""
        pass

    def _callback(self, move_task):
        value = move_task.get()
        self._set_value(value)

    def _set_value(self, value):
        """
        Implementation of specific set actuator logic.
        Args:
            value (float): target value
        """
        pass
