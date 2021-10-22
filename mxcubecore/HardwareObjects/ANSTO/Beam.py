import ast
import logging

from mxcubecore.HardwareObjects.abstract.AbstractBeam import AbstractBeam
from mxcubecore import HardwareRepository as HWR


class Beam(AbstractBeam):

    def __init__(self, name):
        AbstractBeam.__init__(self, name)

        self._beam_size_dict["slits"] = [9999, 9999]
        self._beam_size_dict["aperture"] = [9999, 9999]
        self._beam_position_on_screen = [1224/2, 1024/2]
        self._beam_divergence = (0, 0)

    def init(self):
        self._aperture = self.get_object_by_role("aperture")
        if self._aperture is not None:
            self.connect(
                self._aperture,
                "diameterIndexChanged",
                self.aperture_diameter_changed,
            )

            ad = self._aperture.get_diameter_size() / 1000.0
            self._beam_size_dict["aperture"] = [ad, ad]
            logging.getLogger("HWR").info(
                "Aperture object loaded successfully")

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

    def aperture_diameter_changed(self, name, size):
        """
        Method called when the aperture diameter changes
        Args:
            name (str): diameter name - not used.
            size (float): diameter size in microns
        """
        self._beam_size_dict["aperture"] = [size, size]
        self.evaluate_beam_info()

        self.emit("beamInfoChanged", (self._beam_info_dict))

    def slits_gap_changed(self, size):
        """
        Method called when the slits gap changes
        Args:
            size (tuple): two floats indicates beam size in microns
        """
        self._beam_size_dict["slits"] = size
        self.evaluate_beam_info()

        self.emit("beamInfoChanged", (self._beam_info_dict))

    def set_beam_position_on_screen(self, beam_x, beam_y):
        """
        Sets beam mark position on screen
        #TODO move method to sample_view
        Args:
            beam_x (int): horizontal position in pixels
            beam_y (int): vertical position in pixels
        """
        self._beam_position_on_screen = (beam_x, beam_y)
        self.emit("beamPosChanged", (self._beam_position_on_screen,))

    def get_slits_gap(self):
        """
        Returns: tuple with beam size in microns
        """
        self.evaluate_beam_info()
        return self._beam_size_dict["slits"]

    def set_slits_gap(self, width_microns, height_microns):
        """
        Sets slits gap in microns
        Args:
            width_microns (int):
            height_microns (int):
        """
        if self._slits:
            self._slits.set_horizontal_gap(width_microns / 1000.0)
            self._slits.set_vertical_gap(height_microns / 1000.0)

    def get_aperture_pos_name(self):
        """
        Returns (str): name of current aperture position
        """
        if self._aperture:
            return self._aperture.get_current_pos_name()

    def get_available_size(self):
        aperture_list = self._aperture.get_diameter_size_list()
        return {"type": "enum", "values": aperture_list}

    def get_value(self):
        """
        Gets the value of the beam_width, beam_height,
        beam_shape and label

        Returns
        -------
        result: list
            A list containing beam_width, beam_height,
            beam_shape and label
        """
        result = [self._beam_width, self._beam_height,
                  self._beam_shape, self._beam_label]
        return result

    def get_beam_position_on_screen(self):
        """
        Get beam position in the center of the camera, see e.g.
        ESRFBeam.py

        Returns
        -------
        self._beam_position_on_screen: list
            position of the beam on the screen
        """
        if self._beam_position_on_screen == (0, 0):
            hwr = HWR.get_hardware_repository()
            self._camera = hwr.get_hardware_object(
                "/diffractometer_config/camera")
            _beam_position_on_screen = [
                self._camera.get_width() / 2,
                self._camera.get_height() / 2,
                ]
            self._beam_position_on_screen = _beam_position_on_screen
        return self._beam_position_on_screen

    def set_value(self, size=None):
        """
        Set the beam size
        Parameters
        ----------
        size (list): Width, heigth or
        """
        # TODO: at the moment, set value only changes the
        # diameter size, not the slits size
        # See e.g. ESRFBeam.py
        # self._set_slits_size(size)

        self._set_aperture_size(size)

    def _set_slits_size(self, size=None):
        """
        Sets the silts size
        """
        # TODO: make sure that the new gap values are between
        # the limits specified in the xml file
        self._slits.set_horizontal_gap(size[0])
        self._slits.set_vertical_gap(size[1])
        logging.getLogger("HWR").debug("Slits set correctly")

    def _set_aperture_size(self, size=None):
        """
        Sets the diameter size of the beam

        Parameters
        ----------
        size: int
            diameter of the beam
        """
        self._aperture.set_diameter_size(size)
