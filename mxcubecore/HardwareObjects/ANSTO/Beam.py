import ast
import logging
from enum import Enum
from typing import List, Tuple, Union

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.abstract.AbstractBeam import AbstractBeam


class Beam(AbstractBeam):
    """
    Beam hardware object is used to define final beam size and shape.
    It can include aperture, slits and/or other beam definer
    (lenses or other eq.)

    Attributes
    ----------
    _beam_size_dict : dict
        A dictionary containing information about slits and aperture
    _beam_position_on_screen : list
        List containing the beam position on screen
    _beam_divergence : tuple
        Divergence of the beam

    """

    def __init__(self, name: str) -> None:
        """
        Parameters
        ----------
        name : str
            Name of a Hardware object, e.g. '/beam_info'

        Returns
        -------
        None
        """
        AbstractBeam.__init__(self, name)

        self._beam_size_dict["slits"] = [9999, 9999]
        self._beam_size_dict["aperture"] = [9999, 9999]
        self._beam_position_on_screen = [612, 512]
        self._beam_divergence = (0, 0)

    def init(self) -> None:
        """
        Object initialisation - executed *after* loading contents

        Returns
        -------
        None
        """
        self._aperture = self.get_object_by_role("aperture")
        if self._aperture is not None:
            self.connect(
                self._aperture,
                "diameterIndexChanged",
                self.aperture_diameter_changed,
            )

            ad = self._aperture.get_diameter_size() / 1000.0
            self._beam_size_dict["aperture"] = [ad, ad]
            logging.getLogger("HWR").info("Aperture object loaded successfully")

        self._slits = self.get_object_by_role("slits")
        if self._slits is not None:
            self.connect(self._slits, "valueChanged", self.slits_gap_changed)

            sx, sy = self._slits.get_gaps()
            self._beam_size_dict["slits"] = [sx, sy]
            logging.getLogger("HWR").info("Slits object loaded successfully")

        beam_pos = self.default_beam_pos_on_screen
        self._beam_position_on_screen = list(ast.literal_eval(beam_pos))

        self.evaluate_beam_info()

        self.emit("beamInfoChanged", (self._beam_info_dict))
        self.emit("beamPosChanged", (self._beam_position_on_screen,))

    def aperture_diameter_changed(self, name: str, size: float) -> None:
        """
        Method called when the aperture diameter changes

        Parameters
        ----------
        name : str
            Diameter name - not used.
        size : float
            diameter size in microns

        Returns
        -------
        None
        """
        self._beam_size_dict["aperture"] = [size, size]
        self.evaluate_beam_info()

        self.emit("beamInfoChanged", (self._beam_info_dict))

    def slits_gap_changed(self, size: Tuple[float, float]) -> None:
        """
        Method called when the slits gap changes

        Parameters
        ----------
        size : tuple
            Two floats. Indicates beam size in microns

        Returns
        -------
        None
        """
        self._beam_size_dict["slits"] = size
        self.evaluate_beam_info()

        self.emit("beamInfoChanged", (self._beam_info_dict))

    def set_beam_position_on_screen(self, beam_x: float, beam_y: float) -> None:
        """
        Sets beam mark position on screen
        # TODO move method to sample_view

        Parameters
        ----------
        beam_x : float
            Horizontal position in pixels
        beam_y : float
            Vertical position in pixels

        Returns
        -------
        None
        """
        self._beam_position_on_screen = (beam_x, beam_y)
        self.emit("beamPosChanged", (self._beam_position_on_screen,))

    def get_slits_gap(self) -> List[float]:
        """
        Returns
        --------
        list
            List with beam size in microns
        """
        # TODO: This method has not been tested
        self.evaluate_beam_info()

        return self._beam_size_dict["slits"]

    def set_slits_gap(self, width_microns: float, height_microns: float) -> None:
        """
        Sets slits gap in microns.

        Parameters
        ----------
        width_microns : float
            Gap width in microns
        height_microns : float
            Gap height in microns
        """
        # TODO: This method has not been tested

        if self._slits:
            self._slits.set_horizontal_gap(width_microns / 1000.0)
            self._slits.set_vertical_gap(height_microns / 1000.0)

    def get_aperture_pos_name(self) -> str:
        """
        Gets the aperture position name

        Returns
        -------
        str
            Name of current aperture position
        """
        if self._aperture:
            return self._aperture.get_current_pos_name()

    def get_available_size(self) -> dict:
        """
        Gets the beam available sizes from an xml file.

        Returns
        -------
        dict
            A dictionary containing all avaiable sizes of the beam
        """
        aperture_list = self._aperture.get_diameter_size_list()
        return {"type": "enum", "values": aperture_list}

    def get_value(self) -> Tuple[float, float, Enum, Union[str, None]]:
        """
        Gets the value of the beam_width, beam_height,
        beam_shape and label

        Returns
        -------
        result : tuple
            A tuple containing beam_width, beam_height,
            beam_shape and label
        """
        result = (
            self._beam_width,
            self._beam_height,
            self._beam_shape,
            self._beam_label,
        )
        return result

    def get_beam_position_on_screen(self) -> List[float]:
        """
        Get beam position in the center of the camera, see e.g.
        the beam implementation of the beam class: ESRFBeam.py

        Returns
        -------
        _beam_position_on_screen : list
            Position of the beam on the screen
        """
        if self._beam_position_on_screen == (0, 0):
            hwr = HWR.get_hardware_repository()
            self._camera = hwr.get_hardware_object("/diffractometer_config/camera")
            _beam_position_on_screen = [
                self._camera.get_width() / 2,
                self._camera.get_height() / 2,
            ]
            self._beam_position_on_screen = _beam_position_on_screen
        return self._beam_position_on_screen

    def set_value(self, size: List[float] = None) -> None:
        """
        Set the beam size

        Parameters
        ----------
        size : list
            Width, heigth

        Returns
        -------
        None
        """
        # TODO: at the moment, set_value only changes the
        # diameter size, not the slits size (See e.g. ESRFBeam.py)
        # self._set_slits_size(size)

        self._set_aperture_size(size)

    def _set_slits_size(self, size: List[float] = None) -> None:
        """
        Sets the silts size

        Parameters
        ----------
        size : list
            Width, heigth
        """
        # NOTE: This method has not been tested
        # TODO: make sure that the new gap values are between
        # the limits specified in the xml file

        self._slits.set_horizontal_gap(size[0])
        self._slits.set_vertical_gap(size[1])
        logging.getLogger("HWR").debug("Slits set correctly?")

    def _set_aperture_size(self, size: float = None) -> None:
        """
        Sets the diameter size of the beam

        Parameters
        ----------
        size : float
            diameter of the beam

        Returns
        -------
        None
        """
        self._aperture.set_diameter_size(size)
