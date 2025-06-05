import logging
from enum import (
    Enum,
    unique,
)

from mx3_beamline_library.devices.beam import dmm_stripe

from mxcubecore.BaseHardwareObjects import HardwareObjectState
from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.abstract.AbstractNState import AbstractNState


@unique
class DMMEnum(Enum):
    UNKNOWN = "UNKNOWN"
    OPEN = "OPEN"  # These are used for shutters, not relevant for DMM
    CLOSED = "CLOSED"  # These are used for shutters, not relevant for DMM
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
        self.update_value(self.get_value())

        if settings.BL_ACTIVE:

            self.dmm_stripe_channel = self.add_channel(
                {
                    "type": "epics",
                    "name": "dmm_stripe",
                    "polling": 10000,  # milliseconds
                },
                dmm_stripe.pvname,
            )
            self.dmm_stripe_channel.connect_signal("update", self._value_changed)

    def _value_changed(self, value: int | None) -> None:
        """Emits a valueChanged signal

        Parameters
        ----------
        value : float | None
            The dmm stripe value
        """
        try:
            _value = DMMEnum(value)
        except Exception:
            _value = DMMEnum.UNKNOWN

        self.emit("valueChanged", _value)

    def get_value(self) -> Enum:
        """Get the beam value.
        Returns:
            (Enum): The current position Enum.
        """
        try:
            value = dmm_stripe.get()
        except Exception as e:
            return DMMEnum.UNKNOWN
        return DMMEnum(value)

    def _set_value(self, value: Enum):
        """Set device to value
        Args:
            value (str, int, float or enum): Value to be set.
        """
        logging.getLogger("user_level_log").warning(
            "Setting DMM stripe is not supported."
        )

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
