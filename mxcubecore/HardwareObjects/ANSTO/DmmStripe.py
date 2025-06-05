import logging

from mx3_beamline_library.devices.beam import dmm_stripe

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.abstract.AbstractMotor import AbstractMotor
from mxcubecore.HardwareObjects.ANSTO.EPICSActuator import EPICSActuator


class DmmStripe(AbstractMotor, EPICSActuator):
    """Hardware Object that uses an Ophyd layer to the dmm_stripe.

    Example of xml config file:

    <object class = "ANSTO.dmm_stripe">
    <username>dmm_stripe</username>
    </object>
    """

    def __init__(self, name: str) -> None:
        """Constructor to instantiate OphydEpicsMotor class and it's features.

        Parameters
        ----------
        name : str
            Human readable name of the motor.

        Returns
        -------
        None
        """
        AbstractMotor.__init__(self, name)
        EPICSActuator.__init__(self, name)

        self._wrap_range = None
        # 3 and 4 mean moving and not in position respectively
        self.dmm_mapping = {0: 1.7, 1: 2, 2: 2.7, 3: -1, 4: -1}

    def init(self) -> None:
        """Object initialization - executed after loading contents

        Returns
        -------
        None
        """
        AbstractMotor.init(self)
        EPICSActuator.init(self)

        self.get_limits()
        self.get_velocity()
        self.update_state(self.STATES.READY)

        if settings.BL_ACTIVE:
            # The following channels are used to poll the dmm_stripe PV and the
            # filter_wheel_is_moving PV
            self.dmm_stipe_channel = self.add_channel(
                {
                    "type": "epics",
                    "name": "dmm_stripe",
                    "polling": 10000,  # milliseconds
                },
                dmm_stripe.pvname,
            )
            self.dmm_stipe_channel.connect_signal("update", self._value_changed)

    def _value_changed(self, value: float | None) -> None:
        """Emits a valueChanged signal. Used by self.dmm_stripe_channel

        Parameters
        ----------
        value : float | None
            The dmm_stripe value
        """
        logging.getLogger("HWR").debug(f"{self.name} dmm_stripe value changed: {value}")
        self._value = value
        if value not in [3, 4]:
            # only update the value in the UI if it is not moving or not in position
            self.emit("valueChanged", self.dmm_mapping[self._value])

        if value in [3, 4]:
            self.update_state(self.STATES.BUSY)
            self.update_specific_state(self.SPECIFIC_STATES.MOVING)
        else:
            self.update_state(self.STATES.READY)

    def get_limits(self) -> tuple:
        """Get the limits of a motor.

        Returns
        -------
        tuple
            Low and High limits of a motor.
        """
        self._nominal_limits = (0, 100)
        return self._nominal_limits

    def get_value(self) -> float:
        """Get the current position of the motor.

        Returns
        -------
        float
            The dmm_stripe value
        """

        return self.dmm_mapping[dmm_stripe.get()]

    def _set_value(self, value: float) -> None:
        """Set the dmm stripe to a given value.

        Parameters
        ----------
        value : float
            The dmm_stripe value

        Returns
        -------
        None
        """
        raise NotImplementedError("Setting the dmm stripe value is not implemented. ")

    def abort(self) -> None:
        """Stop the motor and update the new position of the motor.

        Returns
        -------
        None
        """
        pass
