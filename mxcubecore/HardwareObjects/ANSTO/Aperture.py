import logging
from typing import Union

from mxcubecore.HardwareObjects.abstract.AbstractAperture import AbstractAperture

DEFAULT_POSITION_LIST = ("BEAM", "OFF", "PARK")
DEFAULT_DIAMETER_SIZE_LIST = (5, 10, 20, 30, 50, 100)


class Aperture(AbstractAperture):
    """
    Use this class to set the aperture of the beam
    or remove the aperture of the beam.
    """

    def __init__(self, name: str) -> None:
        """
        Parameters
        ----------
        name: str
            Name of a Hardware object, e.g. `/aperture.xml`

        Returns
        -------
        None
        """
        AbstractAperture.__init__(self, name)

    def init(self) -> None:
        """
        Object initialisation - executed *after* loading contents.

        Returns
        -------
        None
        """
        try:
            self._diameter_size_list = eval(self.get_property("diameter_size_list"))
        except BaseException:
            self._diameter_size_list = DEFAULT_DIAMETER_SIZE_LIST
            logging.getLogger("HWR").error(
                "Aperture: no diameter size list defined, using default list"
            )

        try:
            self._position_list = eval(self.get_property("position_list"))
        except BaseException:
            self._position_list = DEFAULT_POSITION_LIST
            logging.getLogger("HWR").error(
                "Aperture: no position list defined, using default list"
            )

        self.set_position_index(0)
        # 100um as default
        self.set_diameter_index(1)

    def set_diameter_size(self, diameter_size: Union[int, str, float]) -> None:
        """
        Sets the diameter size on the beam.

        Parameters
        ----------
        diameter_size : int, float, str
            Selected diameter index
        """
        # make sure the diameter_size is int and not str
        diameter_size = int(diameter_size)

        if diameter_size in self._diameter_size_list:
            self.set_diameter_index(self._diameter_size_list.index(diameter_size))
            logging.getLogger("HWR").info("Diameter changed succesfully")
        else:
            logging.getLogger("HWR").info(
                "Aperture: Selected diameter is not in the diameter list"
            )

    def set_in(self) -> None:
        """
        Sets aperture in the beam.

        Returns
        -------
        None
        """
        self.set_position("BEAM")

    def set_out(self) -> None:
        """
        Removes aperture from the beam.

        Returns
        -------
        None
        """
        self.set_position("OFF")

    def is_out(self) -> bool:
        """
        Determines if the aperture is in the beam.

        Returns
        -------
        bool
            True if aperture is in the beam, otherwise returns false
        """
        return self._current_position_name != "BEAM"
