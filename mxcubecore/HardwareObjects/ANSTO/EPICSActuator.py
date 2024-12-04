"""
Superclass for EPICS actuators

Should be put as the first superclass,
e.g. class MotorMockup(EPICSActuator, AbstractMotor):
"""

import logging

import gevent

from mxcubecore.HardwareObjects.abstract import AbstractActuator


class EPICSActuator(AbstractActuator.AbstractActuator):
    def __init__(self, name: str) -> None:
        """EPICSActuator constructor.

        Parameters
        ----------
        name : str
            Human readable name of the hardware.

        Returns
        -------
        None
        """
        super(EPICSActuator, self).__init__(name)

        self.__move_task = None
        self._nominal_limits = (-1e4, 1e4)

    def init(self) -> None:
        """Object initialization - executed after loading contents

        Returns
        -------
        None
        """
        super(EPICSActuator, self).init()
        self.update_state(self.STATES.READY)

    def _move(self, value: float) -> float:
        """Simulated value change - override as needed

        Must set specific_state as needed, take a non-zero amount of time
        call update_value for intermediate positions
        and return the final value (in case it does not match the input value)

        Parameters
        ----------
        value : float
            target actuator value

        Returns
        -------
        float
            final actuator value (may differ from target value)
        """

    def get_value(self) -> float:
        """Read the actuator position.

        Returns
        -------
        float
            Actuator position.
        """

    def set_value(self, value: float, timeout: int = 0) -> None:
        """Set actuator to absolute value.
        This is NOT the recommended way, but for technical reasons
        overriding is necessary in this particular case.

        Parameters
        ----------
        value : float
            target value
        timeout : int, optional
            If timeout == 0: return at once and do not wait (default).
            If timeout is None: wait forever.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            Value not valid or attemp to set read-only actuator.
        """
        if self.read_only:
            raise ValueError("Attempt to set value for read-only Actuator")
        if self.validate_value(value):
            self.update_state(self.STATES.BUSY)

            if timeout or timeout is None:
                with gevent.Timeout(
                    timeout, RuntimeError(f"Motor {self.username} timed out")
                ):
                    self._set_value(value)
                    self._move(value)
            else:
                self._set_value(value)
                self.__move_task = gevent.spawn(self._move, value)
        else:
            logging.getLogger("user_level_log").error(
                f"{self.username} is out of limits." f" Limits are {self.get_limits()}"
            )

            raise ValueError(f"Invalid value {value}; limits are {self.get_limits()}")

    def abort(self) -> None:
        """Inmediately halt movement. By default self.stop = self.abort

        Returns
        -------
        None
        """

    def _callback(self, move_task) -> None:
        """Callback method to set the current value of the hardware.

        Parameters
        ----------
        move_task : [type]
            [description]

        Returns
        -------
        None
        """
        value = move_task.get()
        self._set_value(value)

    def _set_value(self, value: float) -> None:
        """Implementation of specific set actuator logic.

        Parameters
        ----------
        value : float
            target value

        Returns
        -------
        None
        """
