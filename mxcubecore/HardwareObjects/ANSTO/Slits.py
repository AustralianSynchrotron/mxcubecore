from mxcubecore.HardwareObjects.abstract.AbstractSlits import AbstractSlits


class Slits(AbstractSlits):
    """
    Sets and gets the slit's horizontal and vertical gaps.
    """

    def __init__(self, name: str) -> None:
        """
        Parameters
        ----------
        name : str
            Name of a Hardware object, e.g. `/slits`

        Returns
        -------
        None
        """
        AbstractSlits.__init__(self, name)

    def init(self) -> None:
        """
        Object initialisation - executed *after* loading contents

        Returns
        -------
        None
        """
        # Slits start wide open
        self._value = [1.00, 1.00]
        self._min_limits = [0.001, 0.001]
        self._max_limits = [1, 1]

    def set_horizontal_gap(self, value: float) -> None:
        """
        Sets horizontal gap in microns

        Parameters
        ----------
        value : float
            Target value

        Returns
        -------
        None
        """
        self._value[0] = value
        self.emit("valueChanged", self._value)

    def set_vertical_gap(self, value: float) -> None:
        """
        Sets vertical gap in microns

        Parameters
        ----------
        value : float
            Target value

        Returns
        -------
        None
        """
        self._value[1] = value
        self.emit("valueChanged", self._value)

    def stop_horizontal_gap_move(self) -> None:
        """
        Stops horizontal gap movement

        Returns
        -------
        None
        """
        return

    def stop_vertical_gap_move(self) -> None:
        """
        Stops vertical gap movement

        Returns
        -------
        None
        """
        return
