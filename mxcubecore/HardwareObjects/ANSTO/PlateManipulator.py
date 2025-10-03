import logging
import re

import gevent
import numpy as np
from gevent import sleep
from mx3_beamline_library.plans.calibration.trays.calibrate import (
    define_plane_frame,
    get_positions,
)
from mx3_beamline_library.plans.calibration.trays.plane_frame import PlaneFrame
from mx3_beamline_library.plans.calibration.trays.plate_configs import plate_configs
from mx_robot_library.client import Client
from prefect.server.schemas.states import StateType

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.abstract.AbstractSampleChanger import (
    SampleChanger as AbstractSampleChanger,
)
from mxcubecore.HardwareObjects.abstract.AbstractSampleChanger import SampleChangerState
from mxcubecore.HardwareObjects.abstract.sample_changer import (
    Container,
    Sample,
)

from .Diffractometer import Diffractometer
from .mockup.channels import (
    SimMd3Phase,
    SimMd3State,
)
from .mockup.robot import SimRobot
from .prefect_flows.sync_prefect_client import MX3SyncPrefectClient
from .redis_utils import get_redis_connection


class Xtal(Sample.Sample):
    __NAME_PROPERTY__ = "Name"
    __LOGIN_PROPERTY__ = "Login"

    def __init__(self, drop, index):
        super(Xtal, self).__init__(drop, Xtal._get_xtal_address(drop, index), False)
        self._drop = drop
        self._index = index
        self._set_image_x(None)
        self._set_image_y(None)
        self._set_image_url(None)
        self._set_name(None)
        self._set_login(None)
        self._set_info_url(None)

        self._set_info(False, False, False)
        self._set_loaded(False, False)
        self.present = True

    def _set_name(self, value):
        self._set_property(self.__NAME_PROPERTY__, value)

    def _set_login(self, value):
        self._set_property(self.__LOGIN_PROPERTY__, value)

    def get_login(self):
        return self.get_property(self.__LOGIN_PROPERTY__)

    def get_drop(self):
        return self._drop

    def get_cell(self):
        return self.get_drop().get_cell()

    def get_basket_no(self):
        """
        In this cas we assume a drop is a basket or puck
        """
        return self.get_drop().get_index() + 1

    def get_cell_no(self):
        """
        In this cas we assume a well in the row is a cell
        """
        return self.get_cell().get_row_index() + 1

    @staticmethod
    def _get_xtal_address(drop, index):
        return str(drop.get_address()) + "-" + str(index)

    def get_index(self):
        """
        Descript. : Sample index is calculated relaive to the row (Basket)
                    In this case we assume that in drop is one xtal
                    This should be changed to various num of xtals in the drop
        """
        cell_index = self.get_cell().get_index()
        drops_in_cell_num = self.get_cell().get_drops_no()
        drop_index = self._drop.get_index()
        return cell_index * drops_in_cell_num + drop_index

    def get_container(self):
        return self.get_cell().get_container()

    def get_name(self):
        return "%s%d:%d" % (
            self.get_cell().get_row_chr(),
            self.get_cell().get_index() + 1,
            self._drop.get_index() + 1,
        )


class Drop(Container.Container):
    __TYPE__ = "Drop"

    def __init__(self, cell, drops_num):
        super(Drop, self).__init__(
            self.__TYPE__, cell, Drop._get_drop_address(cell, drops_num), False
        )
        self._cell = cell
        self._drops_num = drops_num

    @staticmethod
    def _get_drop_address(cell, drop_num):
        return str(cell.get_address()) + ":" + str(drop_num)

    def get_cell(self):
        return self._cell

    def get_well_no(self):
        return self.get_index() + 1

    def is_loaded(self):
        """
        Returns if the sample is currently loaded for data collection
        :rtype: bool
        """
        sample = self.get_sample()
        return sample.is_loaded()

    def get_sample(self):
        """
        In this cas we assume that there is one crystal per drop
        """
        sample = self.get_components()
        return sample[0]


class Cell(Container.Container):
    __TYPE__ = "Cell"

    def __init__(self, row, row_chr, col_index, drops_num):
        Container.Container.__init__(
            self, self.__TYPE__, row, Cell._get_cell_address(row_chr, col_index), False
        )
        self._row = row
        self._row_chr = row_chr
        self._col_index = col_index
        self._drops_num = drops_num
        for drop_index in range(self._drops_num):
            drop = Drop(self, drop_index + 1)
            self._add_component(drop)
            xtal = Xtal(drop, drop.get_number_of_components())
            drop._add_component(xtal)
        self._transient = True

    def get_row(self):
        return self._row

    def get_row_chr(self):
        return self._row_chr

    def get_row_index(self):
        return ord(self._row_chr.upper()) - ord("A")

    def get_col(self):
        return self._col_index

    def get_drops_no(self):
        return self._drops_num

    @staticmethod
    def _get_cell_address(row, col):
        return str(row) + str(col)


class PlateManipulator(AbstractSampleChanger):
    """This class is based on the mxcubecore Plate manipulator class.

    It uses simulated channels for the MD3 state and phase if
    settings.BL_ACTIVE is False.
    """

    __TYPE__ = "PlateManipulator"

    def __init__(self, *args, **kwargs):
        super().__init__(self.__TYPE__, False, *args, **kwargs)

    def init(self):
        self.plate_config = self.get_plate_config()

        self.num_cols = self.plate_config["number_of_columns"]
        self.num_rows = self.plate_config["number_of_rows"]
        self.num_drops = self.plate_config["number_of_drops"]

        if settings.BL_ACTIVE:
            self.md3_state = self.add_channel(
                {
                    "type": "exporter",
                    "exporter_address": settings.EXPORTER_ADDRESS,
                    "name": "state",
                },
                "State",
            )
            self.md3_phase = self.add_channel(
                {
                    "type": "exporter",
                    "exporter_address": settings.EXPORTER_ADDRESS,
                    "name": "phase",
                },
                "CurrentPhase",
            )
            self.robot_client = Client(host=settings.ROBOT_HOST, readonly=False)

        else:
            self.md3_state = SimMd3State()
            self.md3_phase = SimMd3Phase()
            self.robot_client = SimRobot()

        self._init_sc_contents()

        super().init()

        self.update_info()

        self.diffractometer: Diffractometer = self.get_object_by_role("diffractometer")

    def _init_sc_contents(self) -> None:
        """
        Initializes the sample changer contents by creating a grid of baskets, cells, and drops.

        Returns
        -------
        None
        """
        if self.num_rows is None:
            return
        self._set_info(False, None, False)
        self._clear_components()
        for row in range(self.num_rows):
            # row is like a basket
            basket = Container.Basket(self, row + 1, samples_num=0, name="Row")
            present = True
            datamatrix = ""
            scanned = False
            basket._set_info(present, datamatrix, scanned)
            self._add_component(basket)

            for col in range(self.num_cols):
                cell = Cell(basket, chr(65 + row), col + 1, self.num_drops)
                basket._add_component(cell)
        self._set_state(SampleChangerState.Ready)

    def get_loaded_sample(self) -> Xtal | None:
        """
        Gets the currently loaded sample based on the current drop location stored in redis.

        Returns
        -------
        Xtal | None
            The currently loaded sample if available, otherwise None.
        """
        for smp in self.get_sample_list():
            smp: Xtal
            if smp.is_loaded():
                return smp
        return None

    def load(
        self,
        sample: str | None = None,
        sample_order: list | None = None,
        wait: bool = True,
    ) -> None:
        """
        Load a sample.

        Parameters
        ----------
        sample : str | None
            The address of the sample to load, in the format 'B7:1-0'
        sample_order : list | None
            The order in which to load samples. Not used for trays
        wait : bool
            Whether to wait for the load operation to complete.

        Returns
        -------
        None
        """
        self.assert_not_charging()
        sample: Xtal = self._resolve_component(sample)
        return self._execute_task(
            SampleChangerState.Loading, wait, self._do_load, sample
        )

    def assert_not_charging(self) -> None:
        """
        Checks if the sample changer is not currently charging or moving.
        If it is, an exception is raised.

        Raises
        ------
        Exception
            If the sample changer is currently charging or moving, an exception is raised.
        """
        current_phase = self.md3_phase.get_value()
        current_state = self.md3_state.get_value()
        if current_phase == "Transfer" or current_state != "Ready":
            logging.getLogger("user_level_log").error(
                f"The current md3 phase is {current_phase} and the current md3 state is {current_state}."
                "Wait until the md3 is ready and not in transfer phase."
            )
            raise Exception(
                "Sample changer is currently charging or moving. Please wait until it is ready."
            )

    def _do_load(self, new_sample: Xtal) -> None:
        """
        Moves the tray to the new_sample position and updates the loaded sample state.
        Called by the load method.

        Parameters
        ----------
        new_sample : Xtal
            The sample to load, which should be an instance of the Xtal class.

        Raises
        ------
        Exception
            If there is an error during the loading process, an exception is raised.
        """
        try:
            sample_str = new_sample.address[:-2]  # e.g. 'B7:1'

            old_sample = self.get_loaded_sample()
            if old_sample != new_sample:

                gevent.sleep(0.01)
                while self.md3_state.get_value().lower() != "ready":
                    gevent.sleep(0.01)

                self.move_to_well_spot(well_input=sample_str)

                gevent.sleep(0.1)
                while self.md3_state.get_value().lower() != "ready":
                    gevent.sleep(0.1)

                with get_redis_connection() as redis_connection:
                    redis_connection.set("current_drop_location", sample_str)

                if old_sample is not None:
                    old_sample._set_loaded(False, True)
                    self._trigger_loaded_sample_changed_event(old_sample)
                    gevent.sleep(0.01)
                if new_sample is not None:
                    new_sample._set_loaded(True, True)
                    self._trigger_loaded_sample_changed_event(new_sample)

                self.update_info()

        except Exception as e:
            logging.getLogger("user_level_log").error(
                f"Error loading sample {new_sample.address}: {str(e)}"
            )
            raise e

    def _do_unload(self, sample_slot: Xtal | None = None) -> None:
        """
        Resets the loaded sample state and deletes the current drop location from redis

        Parameters
        ----------
        sample_slot : Xtal | None
            The sample to unload. Not used in this implementation

        Returns
        -------
        None
        """
        prefect_client = MX3SyncPrefectClient(
            name=settings.UNMOUNT_TRAY_DEPLOYMENT_NAME,
            parameters={},
        )

        response = prefect_client.trigger_flow(wait=True)
        if response.state.type != StateType.COMPLETED:
            logging.getLogger("user_level_log").error(
                f"Failed to unmount tray: {response.state.message}"
            )
            raise RuntimeError(response.state.message)
        self._reset_loaded_sample()
        self._trigger_loaded_sample_changed_event(None)

    def _reset_loaded_sample(self) -> None:
        """
        Resets the loaded sample state for all samples in the tray
        and deletes the current drop location from redis.

        Returns
        -------
        None
        """
        for smp in self.get_sample_list():
            smp._set_loaded(False)

        with get_redis_connection() as redis_connection:
            redis_connection.delete("current_drop_location")
        self._trigger_loaded_sample_changed_event(None)

    def _do_update_info(self) -> None:
        """
        Updates plate info and sample list and sample changer state.
        This function is called every second

        Returns
        -------
        None
        """
        self._update_loaded_sample()
        self._update_sample_changer_state()

    def _update_loaded_sample(self) -> None:
        """
        Updates the loaded sample based on the current drop location

        Returns
        -------
        None
        """
        sample_list = self.get_sample_list()

        with get_redis_connection(decode_response=True) as redis_connection:
            drop_location = redis_connection.get("current_drop_location")
        if drop_location is None:
            # No sample loaded, reset all samples
            for sample in sample_list:
                sample: Xtal
                sample._set_loaded(loaded=False, has_been_loaded=False)
            return

        for sample in sample_list:
            sample: Xtal
            if sample.address[:-2] == drop_location:
                sample._set_loaded(loaded=True, has_been_loaded=True)
                sample._set_info(present=True, id=sample.id, scanned=False)
            else:
                sample._set_loaded(loaded=False, has_been_loaded=False)

    def get_sample_list(self) -> list[Xtal]:
        """
        Returns a list of all samples in the plate.

        Returns
        -------
        list[Xtal]
            A list of Sample objects representing the samples in the plate.
        """
        sample_list = []
        for basket in self.get_components():
            if isinstance(basket, Container.Basket):
                for cell in basket.get_components():
                    if isinstance(cell, Cell):
                        for drop in cell.get_components():
                            drop: Drop
                            sample_list.append(drop.get_sample())
        return sample_list

    def is_mounted_sample(self, sample_location) -> bool:
        """Checks if a sample is currently mounted in the sample changer.

        Parameters
        ----------
        sample_location : str
            The address of the sample to check, in the format 'B7:1-0'

        Returns
        -------
        bool
            True if the sample is mounted, False otherwise.
        """
        if (
            self.robot_client.status.state.goni_plate() is not None
            and self.get_loaded_sample() is not None
        ):
            return True
        return False

    def get_plate_info(self) -> dict:
        """
        Returns a dictionary with plate information. Some of this information
        is shown in the plate manipulator maintenance tab.

        Returns
        -------
        dict
            A dictionary containing the plate information
        """
        plate_info_dict = {}
        plate_info_dict["num_cols"] = self.num_cols
        plate_info_dict["num_rows"] = self.num_rows
        plate_info_dict["num_drops"] = self.num_drops
        plate_info_dict["plate_label"] = ""
        plate_info_dict["plate_barcode"] = self._get_barcode_of_mounted_tray()

        return plate_info_dict

    def move_to_crystal_position(self, crystal_uuid):
        """
         Descript. : Move Diff to crystal position
         Get crystal_uuid from processing plan for loaded sample/drop
        #"""
        # This is where we can unblur the image after moving to the position

        self.update_info()

    def _update_sample_changer_state(self) -> None:
        """
        Updates the sample changer state based on the md3 state.

        Returns
        -------
        None
        """
        md3_state = self.md3_state.get_value()
        current_phase = self.md3_phase.get_value()
        _state: int = SampleChangerState.Unknown
        if md3_state == "Ready":
            _state = SampleChangerState.Ready
        elif md3_state == "Fault":
            _state = SampleChangerState.Moving
        elif md3_state == "Moving":
            _state = SampleChangerState.Moving
        elif md3_state == "Alarm":
            _state = SampleChangerState.Alarm
        else:
            _state = SampleChangerState.Unknown

        if md3_state == "Ready" and self.has_loaded_sample():
            _state = SampleChangerState.Loaded

        if md3_state == "Ready" and current_phase == "Transfer":
            _state = SampleChangerState.Charging

        _last_state = self.state
        if _state != _last_state:
            self._set_state(
                state=_state,
                status=SampleChangerState.tostring(_state),
            )

    def _read_state(self):
        return "ready"

    def _ready(self):
        return True

    def _get_barcode_of_mounted_tray(self) -> str:
        """
        Gets the barcode of the mounted tray using the mx-robot-library.
        Attempts to get the mounted tray up to 3 times, with a 0.5 second delay

        Returns
        -------
        str
            The barcode of the mounted tray

        Raises
        ------
        QueueExecutionException
            An exception if the tray cannot be read from the robot library
        """
        for attempt in range(3):
            try:
                loaded_trays = self.robot_client.status.get_loaded_trays()
                mounted_tray = self.robot_client.status.state.goni_plate
                break
            except Exception:
                if attempt < 2:
                    msg = "Failed to get loaded trays or mounted tray using the robot library, retrying in 0.5 seconds."
                    logging.getLogger("HWR").warning(msg)
                    sleep(0.5)
                else:
                    return "No barcode found"
        barcode = None
        if mounted_tray is not None:
            for tray in loaded_trays:
                if tray[0] == mounted_tray.id:
                    # NOTE: The robot returns the barcode as e.g ASP-3018,
                    # but the data layer expects the format ASP3018
                    barcode = tray[1].replace("-", "")
        else:
            return "No barcode found"

        if barcode is None:
            return "No barcode found"
        return barcode

    def _do_abort(self):
        self.robot_client.common.abort()

    def move_to_well_spot(
        self,
        well_input: str,
    ):
        """
        Move the diffractometer to the specified well and spot number on the tray.

        Parameters
        ----------
        well_input : str
            The well and spot number in the format 'A4:2', where 'A4' is the
            well and '2' is the spot number (1-4).
        plate_type : Literal
            The type of plate being used. Must be one of 'swissci_lowprofile',
            'mitegen_insitu', 'swissci_highprofile', or 'mrc'.
        """

        match = re.match(r"^([A-Ia-i][0-9]{1,2}):(\d)$", well_input)
        if not match:
            raise ValueError(
                f"Invalid input: {well_input}. Format should be like 'A4:2'"
            )

        well_label = match.group(1).upper()
        spot_num = int(match.group(2))

        if not (1 <= spot_num <= 4):
            raise ValueError("Spot number must be 1 to 4")

        # Get all 4 sub-positions from the redis calibration plane
        with get_redis_connection(decode_response=False) as redis_connection:
            res = redis_connection.hgetall("tray_calibration_params")

        if not res:
            logging.getLogger("user_level_log").info("Using default calibration points")
            plane = define_plane_frame(self.plate_config["calibration_points"])
        else:

            origin = np.array(list(map(float, res[b"origin"].decode().split(","))))
            u_axis = np.array(list(map(float, res[b"u_axis"].decode().split(","))))
            v_axis = np.array(list(map(float, res[b"v_axis"].decode().split(","))))

            plane = PlaneFrame(origin, u_axis, v_axis)

        positions = get_positions(well_label, plane, self.plate_config)
        selected = positions[spot_num - 1]["motor_pos"]

        # Unpack and move motors
        depth_offset = self.plate_config["depth"]
        print(depth_offset)
        x, y, z = selected

        target_position = {
            "sampy": z + depth_offset,
            "phiy": x,
            "plate_translation": y,
        }
        self.diffractometer.move_motors(target_position)

        logging.getLogger("HWR").info(
            f"Moved to {well_label} spot {spot_num}: x={x:.3f}, y={y:.3f}, z={z:.3f}"
        )

    # Not implemented methods
    def _do_reset(self):
        pass

    def _do_scan(self, component, recursive):
        pass

    def _do_change_mode(self, mode):
        pass

    def sync_with_crims(self):
        pass

    def get_room_temperature_mode(self):
        return True

    def _do_select(self, component):
        pass

    def get_plate_config(
        self,
    ) -> dict:
        """
        Gets the plate type from redis, and returns the corresponding plate configuration

        Returns
        -------
        dict
            The plate configuration dictionary.
        """
        with get_redis_connection(decode_response=True) as redis_connection:
            plate_type = redis_connection.get("plate_type")

        if plate_type is None:
            msg = "No plate type found in Redis'."
            logging.getLogger("user_level_log").error(msg)
            raise ValueError(msg)

        allowed_plate_types = [
            "swissci_lowprofile",
            "mitegen_insitu",
            "swissci_highprofile",
            "mrc",
        ]
        if plate_type not in allowed_plate_types:
            msg = f"Unknown plate type: {plate_type}. Supported types are {allowed_plate_types}"
            logging.getLogger("user_level_log").error(msg)
            raise ValueError(msg)

        if plate_type == "mitegen_insitu":
            config = plate_configs.mitegen_insitu
        elif plate_type == "swissci_highprofile":
            config = plate_configs.swissci_highprofile
        elif plate_type == "mrc":
            config = plate_configs.mrc
        elif plate_type == "swissci_lowprofile":
            config = plate_configs.swissci_lowprofile
        return config
