from mxcubecore.HardwareObjects.abstract.AbstractMotor import AbstractMotor
from mxcubecore.HardwareObjects.ASLS.EPICSActuator import EPICSActuator
import ophyd
import logging
import time


class OphydEpicsMotor(AbstractMotor, EPICSActuator):
    def __init__(self, name):
        AbstractMotor.__init__(self, name)
        EPICSActuator.__init__(self, name)
        self._wrap_range = None
        self.device = None

    def init(self):
        self.device = ophyd.EpicsMotor(self.pv_prefix, name=self.motor_name)
        self.device.wait_for_connection(timeout=5)

        """ Initialization method """
        AbstractMotor.init(self)
        EPICSActuator.init(self)

        self.get_limits()
        self.get_velocity()
        self.update_state(self.STATES.READY)

    def _move(self, value):
        self.update_specific_state(self.SPECIFIC_STATES.MOVING)

        while self.device.moving:
            time.sleep(0.2)
            self.update_state(self.STATES.BUSY)
            current_value = self.get_value()
            self.update_value(current_value)

        self.update_state(self.STATES.READY)
        return value

    def abort(self):
        self.device.stop(success=True)
        self._set_value(self.get_value())
        self.update_state(self.STATES.READY)

    def get_limits(self):
        self._nominal_limits = self.device.limits

        logging.getLogger("HWR").info(
            f"Motor {self.motor_name} limits: {self._nominal_limits}")
        return self._nominal_limits

    def get_velocity(self):
        self._velocity = self.device.velocity.get()
        return self._velocity

    def set_velocity(self, value):
        self.device.velocity.put(value)

    def get_value(self):
        return self.device.user_readback.get()

    def _set_value(self, value):
        self.device.user_setpoint.put(value, wait=False)

        self.update_value(value)
        self.update_state(self.STATES.READY)
