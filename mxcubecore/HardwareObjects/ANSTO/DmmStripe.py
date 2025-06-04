
import random
import time
import logging

from mxcubecore.HardwareObjects.abstract.AbstractNState import AbstractNState
from mxcubecore.HardwareObjects.mockup.ActuatorMockup import ActuatorMockup

from enum import (
    Enum,
    unique,
)
from mxcubecore.BaseHardwareObjects import HardwareObjectState
from mxcubecore.HardwareObjects.ANSTO.EPICSActuator import EPICSActuator
from mx3_beamline_library.devices.beam import dmm_stripe
from mxcubecore.BaseHardwareObjects import HardwareObject
from mxcubecore.HardwareObjects.abstract.AbstractDetector import AbstractDetector
from mxcubecore.configuration.ansto.config import settings



@unique
class DMMEnum(Enum):
    """Defines only the compulsory unknown."""

    UNKNOWN = "UNKNOWN"
    DUMMY = "DUMMY" # These are used for shutters, not relevant for DMM
    DUMMY2 = "DUMMY2" # These are used for shutters, not relevant for DMM
    STRIPE_1_7 = 0
    STRIPE_2 = 1
    STRIPE_2_7 = 2
    MOVING = 3
    NOT_IN_POSITION = 4

class DmmStripe(AbstractNState):
    """BeamDefinerMockup class"""

    def __init__(self, *args):
        super().__init__(*args)

    def init(self):
        super().init()
        self.VALUES = DMMEnum
        # self.update_value(self.get_value())
        self.update_value(DMMEnum(dmm_stripe.get()))

        if settings.BL_ACTIVE:
            # The following channels are used to poll the transmission PV and the
            # filter_wheel_is_moving PV
            self.dmm_stripe_channel = self.add_channel(
                {
                    "type": "epics",
                    "name": "dmm_stripe",
                    "polling": 1000,  # milliseconds
                },
                dmm_stripe.pvname,
            )
            self.dmm_stripe_channel.connect_signal("update", self._value_changed)

    def _value_changed(self, value: int | None) -> None:
        """Emits a valueChanged signal

        Parameters
        ----------
        value : float | None
            The transmission value
        """
        logging.getLogger("HWR").info(f"DMM stripe value changed: {value}")
        try:
            _value = DMMEnum(value)
        except ValueError:
            _value = DMMEnum.UNKNOWN
        logging.getLogger("HWR").info(f"DMM all good: {_value}")

        self.emit("valueChanged", _value)
        logging.getLogger("HWR").info(f"DMM all good: {_value}")


    def get_value(self) -> Enum:
        """Get the beam value.
        Returns:
            (Enum): The current position Enum.
        """
        value =  dmm_stripe.get()
        return DMMEnum(value)

    def _set_value(self, value: Enum):
        """Set device to value
        Args:
            value (str, int, float or enum): Value to be set.
        """
        logging.getLogger("user_level_log").warning("Setting DMM stripe is not supported.")

    
    def get_state(self) -> HardwareObjectState:
        """Gets the state of the detector

        Returns
        -------
        HardwareObjectState
            The state of the detector
        """


        # if state in busy_list:
        #     self._state = HardwareObjectState.BUSY
        # elif state == "error":
        #     self._state = HardwareObjectState.FAULT
        # elif state in ["na", "test"]:
        #     self._state = HardwareObjectState.UNKNOWN
        # elif state in ["ready", "idle"]:
        self._state = HardwareObjectState.READY
        self.update_state(self._state)
        return self._state
