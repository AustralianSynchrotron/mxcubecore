import logging
import re
from abc import (
    ABC,
    abstractmethod,
)
from http import HTTPStatus
from time import sleep
from typing import Literal
from urllib.parse import urljoin

import httpx
from mx_robot_library.client import Client
from scipy.constants import (
    Planck,
    electron_volt,
    speed_of_light,
)

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException
import pickle

from ..mockup.robot import SimRobot
from ..redis_utils import get_redis_connection
from ..Resolution import Resolution
from .schemas.data_layer import PinRead
from .schemas.full_dataset import FullDatasetDialogBox
from .schemas.grid_scan import GridScanDialogBox
from .schemas.one_shot import OneShotDialogBox
from .schemas.screening import ScreeningDialogBox


class AbstractPrefectWorkflow(ABC):
    """Abstract class to run Bluesky plans as part of
    an mxcubecore workflow. Classes created using this abstract class are meant
    to be used by the BlueskyWorkflow class.

    Attributes
    ----------
    prefect_flow_aborted : bool
        True if a bluesky plan is aborted, False otherwise. False, by default.
    mxcubecore_workflow_aborted : bool
        True if a mxcubecore workflow is aborted, False otherwise. False, by default.
    """

    def __init__(self, state, resolution: Resolution) -> None:
        """
        Parameters
        ----------
        state : State
            The state of the PrefectWorkflow class. See the State class in
            BlueskyWorkflow for details
        resolution : Resolution
            The resolution hardware object used to map resolution to
            detector distance

        Returns
        -------
        None
        """

        super().__init__()
        self._state = state
        self.resolution = resolution

        self.prefect_flow_aborted = False
        self.mxcubecore_workflow_aborted = False

        if settings.BL_ACTIVE:
            self.robot_client = Client(host=settings.ROBOT_HOST, readonly=False)
        else:
            self.robot_client = SimRobot()

        try:
            self.loaded_pucks = self.robot_client.status.get_loaded_pucks()
        except Exception as e:
            logging.getLogger("HWR").warning(
                f"Failed to load pucks using the robot library: {e}. Retrying in 0.5 seconds."
            )
            sleep(0.5)
            self.loaded_pucks = self.robot_client.status.get_loaded_pucks()

        self._collection_type = None  # To be overridden by inheriting classes

    @abstractmethod
    def run(self) -> None:
        """
        Runs a prefect flow. Here the flow should be executed with asyncio.run()
        """

    @abstractmethod
    def dialog_box(self) -> dict:
        """
        Workflow dialog box. Returns a dictionary that follows a JSON schema

        Returns
        -------
        dialog : dict
            A dictionary that follows a JSON schema.
        """
        dialog = {
            "properties": {
                "name": {
                    "title": "Task name",
                    "type": "string",
                    "minLength": 2,
                    "default": "Test",
                },
            },
            "required": ["name"],
            "dialogName": "My Workflow parameters",
        }
        return dialog

    @property
    def prefect_flow_aborted(self) -> bool:
        """
        Gets the state of the bluesky plan

        Returns
        -------
        self._value : bool
            The state of the bluesky plan
        """
        return self._prefect_flow_aborted

    @prefect_flow_aborted.setter
    def prefect_flow_aborted(self, value: bool) -> None:
        """
        Sets the state of the bluesky plan

        Parameters
        ----------
        value : bool
            The state of the bluesky plan

        Returns
        -------
        None
        """
        self._prefect_flow_aborted = value

    @property
    def mxcubecore_workflow_aborted(self) -> bool:
        """
        Gets the state of the mxcubecore workflow

        Returns
        -------
        self._value: bool
            The state of the mxcubecore workflow
        """
        return self._mxcubecore_workflow_aborted

    @mxcubecore_workflow_aborted.setter
    def mxcubecore_workflow_aborted(self, value: bool) -> None:
        """
        Sets the state of the mxcubecore workflow

        Returns
        -------
        None
        """
        self._mxcubecore_workflow_aborted = value

    @property
    def state(self):
        """
        Gets the state of the workflow

        Returns
        -------
        _state : State
            The state of the workflow
        """
        return self._state

    @state.setter
    def state(self, new_state) -> None:
        """
        Sets the state of the workflow

        Parameters
        ----------
        new_state : State
            The state of the workflow

        Returns
        -------
        None
        """
        self._state = new_state

    def _get_epn_string(self) -> str:
        """
        Gets the EPN string from Redis

        Returns
        -------
        str
            The EPN string

        Raises
        ------
        QueueExecutionException
            An exception if the EPN string is not set in Redis
        """
        with get_redis_connection() as redis_connection:
            epn_string: str | None = redis_connection.get("epn")
            if epn_string is None:
                raise QueueExecutionException("EPN string is not set in Redis", self)
            return epn_string

    def _get_pin_model_of_mounted_sample_from_db(self) -> PinRead:
        """Gets the pin model from the mx-data-layer-api

        Returns
        -------
        PinRead
            A PinRead pydantic model

        Raises
        ------
        QueueExecutionException
            An exception if Pin cannot be read from the data layer
        """
        logging.getLogger("HWR").info(
            "Getting barcode from mounted pin using the mx-robot-api"
        )
        port, barcode = self._get_barcode_and_port_of_mounted_pin()

        epn_string = self._get_epn_string()

        logging.getLogger("HWR").info(
            f"Getting pin id from the mx-data-layer-api for port {port}, "
            f"barcode {barcode}, and epn_string {epn_string}"
        )

        with httpx.Client() as client:
            r = client.get(
                urljoin(
                    settings.DATA_LAYER_API,
                    f"/samples/pins?filter_by_port={port}&filter_by_puck_barcode={barcode}&filter_by_visit_identifier={epn_string}",
                )
            )
            if r.status_code == HTTPStatus.OK:
                response = r.json()
                if len(response) == 1:
                    return PinRead.model_validate(r.json()[0])
                elif len(response) > 1:
                    msg = f"There are multiple ({len(response)}) pins with the same barcode {barcode}, port {port}, and epn {epn_string}"
                    logging.getLogger("user_level_log").error(msg)
                    raise QueueExecutionException(msg, self)
                elif len(response) == 0:
                    msg = f"No pin found with barcode {barcode}, port {port}, and epn {epn_string}"
                    logging.getLogger("user_level_log").error(msg)
                    raise QueueExecutionException(msg, self)

            else:
                msg = f"Failed to get pin by barcode {barcode}, port {port}, and epn {epn_string} from the data layer API"
                logging.getLogger("user_level_log").error(msg)
                raise QueueExecutionException(msg, self)

    def _get_barcode_and_port_of_mounted_pin(self) -> tuple[int, str]:
        """
        Gets the barcode and port of the mounted pin using the mx-robot-library

        Returns
        -------
        tuple[int, str]
            The port and barcode of the mounted pin

        Raises
        ------
        QueueExecutionException
            Raises an exception is no pin is currently mounted
        """

        mounted_sample = self.robot_client.status.state.goni_pin
        if mounted_sample is not None:
            for puck in self.loaded_pucks:
                if puck.id == mounted_sample.puck.id:
                    # NOTE: The robot returns the barcode as e.g ASP-3018,
                    # but the data layer expects the format ASP3018
                    return (mounted_sample.id, puck.name.replace("-", ""))

        else:
            logging.getLogger("user_level_log").error("No pin mounted on the goni")
            raise QueueExecutionException("No pin mounted on the goni", self)

    def _save_dialog_box_params_to_redis(
        self,
        dialog_box: (
            ScreeningDialogBox
            | FullDatasetDialogBox
            | GridScanDialogBox
            | OneShotDialogBox
        ),
    ) -> None:
        """
        Save the last set parameters from the dialog box to Redis.

        Parameters
        ----------
        dialog_box : ScreeningDialogBox | FullDatasetDialogBox | GridScanDialogBox | OneShotDialogBox
            A dialog box pydantic model
        """
        with get_redis_connection() as redis_connection:
            for key, value in dialog_box.model_dump(exclude_none=True).items():
                if isinstance(value, bool):
                    value = 1 if value else 0
                redis_connection.set(f"{self._collection_type}:{key}", value)

    def _get_dialog_box_param(
        self,
        parameter: Literal[
            "exposure_time",
            "omega_range",
            "number_of_frames",
            "processing_pipeline",
            "crystal_counter",
            "photon_energy",
            "resolution",
            "md3_alignment_y_speed",
            "transmission",
            "auto_create_well"
        ],
    ) -> str | int | float:
        """
        Retrieve a parameter value from Redis.

        Parameters
        ----------
        Literal[
            "exposure_time",
            "omega_range",
            "number_of_frames",
            "processing_pipeline",
            "crystal_counter",
            "photon_energy",
            "resolution",
            "md3_alignment_y_speed",
            "transmission",
            "auto_create_well"
        ]
            A parameter saved in redis

        Returns
        -------
        str | int | float
            The last value set in redis for a given parameter
        """
        with get_redis_connection() as redis_connection:

            
            value =  redis_connection.get(f"{self._collection_type}:{parameter}")

            if parameter == "auto_create_well":
                return bool(int(value))
            else:
                return value

    def _resolution_to_distance(self, resolution: float, energy: float) -> float:
        """
        Converts resolution to distance. The mapping is always done
        at 16M mode

        Parameters
        ----------
        resolution : float
            Resolution in Angstrom
        energy : float
            Energy in keV

        Returns
        -------
        float
            The distance in meters
        """
        wavelength = self._keV_to_angstrom(energy)
        return (
            self.resolution.resolution_to_distance(
                resolution=resolution, wavelength=wavelength
            )
            / 1000
        )

    def _keV_to_angstrom(self, energy_keV: float) -> float:
        """
        Converts energy in keV to wavelength in Angstrom

        Parameters
        ----------
        energy_keV : float
            Energy in keV

        Returns
        -------
        float
            Wavelength in Angstrom
        """
        energy_joules = energy_keV * 1000 * electron_volt
        wavelength_SI = Planck * speed_of_light / (energy_joules)
        wavelength_angstrom = wavelength_SI * 1e10
        return wavelength_angstrom

    def _set_detector_roi_mode(self, roi_mode: Literal["4M", "disabled"]) -> None:
        """
        Sets the detector roi mode

        Parameters
        ----------
        roi_mode : Literal["4M", "disabled"]
            The roi mode

        Returns
        -------
        None

        Raises
        ------
        QueueExecutionException
            Raises an exception if the response is different from HTTPStatus.OK
        """
        with httpx.Client() as client:
            r = client.get(
                urljoin(settings.SIMPLON_API, "/detector/api/1.8.0/config/roi_mode")
            )

            if r.status_code != HTTPStatus.OK:
                raise QueueExecutionException(
                    message="Failed to communicate with the SIMPLON API", origin=self
                )

            if r.json()["value"] != roi_mode:
                logging.getLogger("HWR").info(
                    f"Changing detector roi mode to {roi_mode}"
                )
                client.put(
                    urljoin(
                        settings.SIMPLON_API, "/detector/api/1.8.0/config/roi_mode"
                    ),
                    json={"value": roi_mode},
                )

    def get_head_type(
        self,
    ) -> Literal["SmartMagnet", "MiniKappa", "Plate", "Permanent", "Unknown"]:
        """
        Get the md3 head type from the md3 and saved it to redis

        Returns
        -------
        None
        """
        with get_redis_connection() as redis_connection:
            head_type = redis_connection.get("mxcube:md3_head_type")

        if head_type is None:
            raise ValueError("mxcube:md3_head_type is not set in redis")

        return head_type

    # Database tray related methods
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
                    msg = "Failed to get loaded trays or mounted tray using the robot library"
                    logging.getLogger("HWR").error(msg)
                    raise QueueExecutionException(msg, self)
        barcode = None
        if mounted_tray is not None:
            for tray in loaded_trays:
                if tray[0] == mounted_tray.id:
                    # NOTE: The robot returns the barcode as e.g ASP-3018,
                    # but the data layer expects the format ASP3018
                    barcode = tray[1].replace("-", "")
        else:
            msg = "No tray mounted on the goni"
            logging.getLogger("user_level_log").error(msg)
            raise QueueExecutionException(msg, self)

        if barcode is None:
            msg = "No barcode found for the mounted tray"
            logging.getLogger("user_level_log").error(msg)
            raise QueueExecutionException(msg, self)
        return barcode

    def _get_current_drop_location(self) -> tuple[int, int, int]:
        with get_redis_connection() as redis_connection:
            current_drop_location = redis_connection.get("current_drop_location")
            if current_drop_location is None:
                msg = "current_drop_location redis key does not exist"
                logging.getLogger("user_level_log").error(msg)
                raise QueueExecutionException(msg, self)

        return self._parse_plate_address(current_drop_location)

    def _get_well_id_of_mounted_tray(self, project_name: str|None=None) -> int:
        """Gets the well id from the mx-data-layer-api

        Returns
        -------
        int
            The well id

        Raises
        ------
        QueueExecutionException
            An exception if Tray cannot be read from the data layer
        """
        logging.getLogger("HWR").info(
            "Getting barcode from mounted tray using the mx-robot-api"
        )
        barcode = self._get_barcode_of_mounted_tray()

        epn_string = self._get_epn_string()

        row, column, drop = self._get_current_drop_location()

        # FIXME: This will be changed to numbers in the data layer
        if drop == 1:
            drop = "left"
        elif drop == 2:
            drop = "right"
        elif drop == 3:
            drop = "middle"

        if project_name is not None:
            well_id = self._add_well_to_db(barcode, epn_string, column, row, drop, project_name)
        else:
            well_id = self._get_well_id(barcode, epn_string, column, row, drop)

        return well_id

    def _get_well_id(self, barcode:str, epn_string: str, column: int, row: str, drop: str) -> int:
        logging.getLogger("HWR").info(
            f"Getting well id for barcode {barcode}, epn_string {epn_string}, column {column}, row {row}, and drop {drop}"
        )
        r = httpx.get(
            urljoin(
                settings.DATA_LAYER_API,
                f"/samples/wells?filter_by_tray_barcode={barcode}&filter_by_visit_identifier={epn_string}&filter_by_column={column}&filter_by_row={row}&filter_by_drop={drop}",
            )
        )
        if r.status_code == HTTPStatus.OK:
            response = r.json()
            if len(response) == 1:
                return response[0]["id"]
            elif len(response) > 1:
                msg = f"There are multiple ({len(response)}) wells with the same barcode {barcode}, epn {epn_string}, column {column}, row {row}, and drop {drop}"
                logging.getLogger("user_level_log").error(msg)
                raise QueueExecutionException(
                    msg,
                    self,
                )
            elif len(response) == 0:
                # TODO: Add samples on the fly
                msg = f"No well found with barcode {barcode}, epn {epn_string}, column {column}, row {row}, and drop {drop}"
                logging.getLogger("user_level_log").error(msg)
                raise QueueExecutionException(
                    msg,
                    self,
                )

        else:
            msg = f"Failed to get well by barcode {barcode}, epn {epn_string}, column {column}, row {row}, and drop {drop}"
            logging.getLogger("user_level_log").error(msg)
            raise QueueExecutionException(
                msg,
                self,
            )

    def _parse_plate_address(self, address: str) -> tuple[str, int, int]:
        """
        Parses a plate address in the format 'B7:1' and returns the row letter,
        column (starting from 1), and drop (starting from 1).

        Parameters
        ----------
        address : str
            The address string to parse, e.g. 'B7:1'.

        Returns
        -------
        tuple[str, int, int]
            A tuple containing the row letter, column (from 1), and drop (from 1).
        """
        match = re.match(r"([A-Z])(\d+):(\d+)", address)
        if not match:
            raise QueueExecutionException(
                f"Invalid well address format. Expected format is e.g.'B7:1', not {address}", self)
        row_chr, col_str, drop_str = match.groups()
        row = row_chr.upper()
        col = int(col_str)
        drop = int(drop_str)
        return row, col, drop

    def get_sample_id_of_mounted_sample(self, project_name: str|None=None) -> int:
        """
        Gets the sample id of the mounted sample. The sample id is either the pin id
        or the well id, depending on the head type.

        Returns
        -------
        int
            The sample id of the mounted sample.
        project_id : int | None
            The project id to use when creating a new well (if needed).

        Raises
        ------
        QueueExecutionException
            If the head type is not implemented for getting the sample id.
        """
        head_type = self.get_head_type()

        if head_type == "SmartMagnet":
            sample_id = self._get_pin_model_of_mounted_sample_from_db().id
        elif head_type == "Plate":
            sample_id = self._get_well_id_of_mounted_tray(project_name)
        else:
            msg = f"Head type {head_type} is not implemented for getting sample id"
            logging.getLogger("user_level_log").error(msg)
            raise QueueExecutionException(msg, self)
        return sample_id

    def _get_tray_id_of_mounted_tray(self, barcode: str, epn: str) -> int:

        response = httpx.get(
            urljoin(
                settings.DATA_LAYER_API,
                f"/samples/trays?filter_by_tray_barcode={barcode}&filter_by_visit_identifier={epn}",
            )
        )

        if response.status_code == HTTPStatus.OK:
            data = response.json()
            if len(data) == 1:
                return data[0]["id"]
            elif len(data) > 1:
                msg = f"Multiple trays found for barcode {barcode} and epn {epn}"
                logging.getLogger("user_level_log").error(msg)
                raise QueueExecutionException(msg, self)
            else:
                msg = f"No tray found for barcode {barcode} and epn {epn}"
                logging.getLogger("user_level_log").error(msg)
                raise QueueExecutionException(msg, self)
        else:
            msg = f"Failed to get tray by barcode {barcode} and epn {epn} from the data layer API"
            logging.getLogger("user_level_log").error(msg)
            raise QueueExecutionException(msg, self)

    def _add_well_to_db(self, barcode, epn_string, column, row, drop, project_name: str) -> int:
        """
        Adds a well to the database.

        Returns
        -------
        int
            The id of the created well.
        """
        tray_id = self._get_tray_id_of_mounted_tray(barcode, epn_string)

        projects = self.get_project_and_lab_names()

        project_id = None
        for project in projects:
            if project[0] == project_name:
                project_id = project[1]
                break
        
        if project_id is None:
            logging.getLogger("user_level_log").error(f"Project ID not found for project name {project[0]}")
            raise QueueExecutionException(f"Project ID not found for project name {project[0]}", self)

        payload = {
        "name": "", # The data layer automatically will create a name
        "description": "",
        "type": "sample_well",
        "row": row,
        "column": column,
        "drop": drop,
        "tray_id": tray_id,
        "project_id": project_id,
        }
        response = httpx.post(
            urljoin(settings.DATA_LAYER_API, "/samples/wells"),
            json=payload
        )

        if response.status_code == HTTPStatus.CREATED:
            data = response.json()
            logging.getLogger("HWR").info(f"Well {data['name']} added to the database")
            return data["id"]
        else:
            msg = f"Failed to add well to the database: {response.text}"
            logging.getLogger("user_level_log").error(msg)
            raise QueueExecutionException(msg, self)



    def get_project_and_lab_names(self) -> list[tuple[str, int]]:
        """
        Gets the names and IDs of all projects.

        Returns
        -------
        list[tuple[str, int]]
            A list of tuples containing project names and their IDs.
        """
        with get_redis_connection(decode_response=False) as redis_connection:
            lab_ids = redis_connection.get("lab_ids")
            if lab_ids is None:
                logging.getLogger("user_level_log").warning("No lab IDs found in Redis")
                return []
            else:
                lab_ids = pickle.loads(lab_ids)

        project_and_lab_list = []
        with httpx.Client() as client:
            for lab in lab_ids:
                lab_response = client.get(settings.DATA_LAYER_API + f"/labs/{lab}")
                if lab_response.status_code == HTTPStatus.OK:
                    lab_name = lab_response.json()["name"]
                else:
                    msg = f"Failed to get lab info from the data layer API: {lab_response.text}"
                    logging.getLogger("user_level_log").warning(msg)
                    continue

                response = client.get(settings.DATA_LAYER_API + f"/projects?only_active=true&filter_by_lab={lab}")
                if response.status_code == HTTPStatus.OK:
                    data = response.json()
                    if len(data) > 0:
                        project_and_lab_list.extend([(f"{item['name']} (Lab: {lab_name})", item["id"]) for item in data])
                else:
                    msg = f"Failed to get project names from the data layer API: {response.text}"
                    logging.getLogger("user_level_log").warning(msg)
        return project_and_lab_list

    def _build_plate_dialog_schema(self) -> tuple[dict, dict]:
        """
        Returns plate fields for the dialog schema.

        Returns
        -------
        tuple[dict, dict]
            The properties dict which can be added to the dialog schema,
            and the conditional dict for the project name.
        """
        properties: dict = {
            "auto_create_well": {
                "title": "Auto Create Well",
                "type": "boolean",
                "default": self._get_dialog_box_param("auto_create_well"),
                "widget": "textarea",
            }
        }

        projects_and_labs_names = self.get_project_and_lab_names()
        project_names = []
        for projects in projects_and_labs_names:
            project_names.append(projects[0])

        default_project = self._get_dialog_box_param("project_name")

        project_field: dict = {
            "title": "Project Name",
            "type": "string",
            "enum": project_names,
            "widget": "select",
        }
        if default_project is not None and default_project in project_names:
            project_field["default"] = default_project

        conditional_project = {
            "if": {"properties": {"auto_create_well": {"const": True}}},
            "then": {
                "properties": {"project_name": project_field},
                "required": ["project_name"],
            },
        }

        return properties, conditional_project