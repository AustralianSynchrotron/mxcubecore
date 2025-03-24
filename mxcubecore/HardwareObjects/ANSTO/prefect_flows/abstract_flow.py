import asyncio
import logging
import os
from abc import (
    ABC,
    abstractmethod,
)
from http import HTTPStatus
from os import getenv
from time import (
    perf_counter,
    sleep,
)
from typing import Literal
from urllib.parse import urljoin

import gevent
import httpx
import redis
from mx_robot_library.client import Client

from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from .schemas.data_layer import PinRead
from .schemas.full_dataset import FullDatasetDialogBox
from .schemas.grid_scan import GridScanDialogBox
from .schemas.screening import ScreeningDialogBox
from ..Resolution import Resolution
from scipy.constants import Planck, electron_volt, speed_of_light


ROBOT_HOST = getenv("ROBOT_HOST", "127.0.0.0")
DATA_LAYER_API = getenv("DATA_LAYER_API", "http://0.0.0.0:8088")
EPN_STRING = getenv(
    "EPN_STRING", "my_epn"
)  # TODO: could be obtained from somewhere else


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

        self.robot_client = Client(host=ROBOT_HOST, readonly=False)

        try:
            self.loaded_pucks = self.robot_client.status.get_loaded_pucks()
        except Exception as e:
            logging.getLogger("HWR").warning(
                f"Failed to load pucks using the robot library: {e}. Retrying in 0.5 seconds."
            )
            sleep(0.5)
            self.loaded_pucks = self.robot_client.status.get_loaded_pucks()

        self.REDIS_HOST = os.environ.get("MXCUBE_REDIS_HOST", "mx_redis")
        self.REDIS_PORT = int(os.environ.get("MXCUBE_REDIS_PORT", "6379"))
        self.REDIS_USERNAME = os.environ.get("MXCUBE_REDIS_USERNAME", None)
        self.REDIS_PASSWORD = os.environ.get("MXCUBE_REDIS_PASSWORD", None)
        self.REDIS_DB = int(os.environ.get("MXCUBE_REDIS_DB", "0"))

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

    def get_pin_model_of_mounted_sample_from_db(self) -> PinRead:
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

        logging.getLogger("HWR").info(
            f"Getting pin id from the mx-data-layer-api for port {port}, "
            f"barcode {barcode}, and epn_string {EPN_STRING}"
        )

        with httpx.Client() as client:
            r = client.get(
                urljoin(
                    DATA_LAYER_API,
                    f"/pin/by_barcode_port_and_epn/{port}/{barcode}/{EPN_STRING}",
                )
            )
            if r.status_code != HTTPStatus.OK:
                raise QueueExecutionException(
                    f"Could not get pin by barcode, port, and epn from the data layer API: {r.content}",
                    self,
                )

            return PinRead.model_validate(r.json())

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
            raise QueueExecutionException("No pin mounted on the goni", self)

    def _get_asyncio_event_loop(self, timeout: float = 30):
        """
        Gets the asyncio event loop. If a loop is still running,
        waits until the loop is complete.

        Parameters
        ----------
        timeout : float, optional
            The timeout in seconds, by default 30

        Raises
        ------
        QueueExecutionException
            Raises an exception if the timeout is exceeded
        """
        loop = asyncio.get_event_loop()
        if loop.is_running():
            logging.getLogger("HWR").warning(
                f"Loop is still running, waiting for {timeout} s to complete"
            )
            t = perf_counter()
            while loop.is_running():
                gevent.sleep(1)
                logging.getLogger("HWR").warning(f"Loop is still running")
                if perf_counter() > t + timeout:
                    raise QueueExecutionException("Asyncio Loop is still running", self)
        return loop

    def _get_redis_connection(self) -> redis.StrictRedis:
        """Create and return a Redis connection.

        Returns
        -------
        redis.StrictRedis
            A redis connection
        """
        return redis.StrictRedis(
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
            username=self.REDIS_USERNAME,
            password=self.REDIS_PASSWORD,
            db=self.REDIS_DB,
            decode_responses=True,
        )

    def _save_dialog_box_params_to_redis(
        self, dialog_box: ScreeningDialogBox | FullDatasetDialogBox | GridScanDialogBox
    ) -> None:
        """
        Save the last set parameters from the dialog box to Redis.

        Parameters
        ----------
        dialog_box : ScreeningDialogBox | FullDatasetDialogBox | GridScanDialogBox
            A dialog box pydantic model
        """
        with self._get_redis_connection() as redis_connection:
            for key, value in dialog_box.dict(exclude_none=True).items():
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
            "transmission"
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
            "md3_alignment_y_speed"
            "transmission"
        ]
            A parameter saved in redis

        Returns
        -------
        str | int | float
            The last value set in redis for a given parameter
        """
        with self._get_redis_connection() as redis_connection:
            return redis_connection.get(f"{self._collection_type}:{parameter}")

    def _resolution_to_distance(self, resolution: float, energy: float)-> float:
        """
        Converts resolution 

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
        return self.resolution.resolution_to_distance(resolution=resolution, wavelength=wavelength) / 1000

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
