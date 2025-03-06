import logging
from abc import (
    ABC,
    abstractmethod,
)
from http import HTTPStatus
from os import getenv
from urllib.parse import urljoin

import httpx
from mx_robot_library.client import Client

from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from .schemas.data_layer import PinRead

ROBOT_HOST = getenv("ROBOT_HOST", "127.0.0.0")
DATA_LAYER_API = getenv("DATA_LAYER_API", "http://0.0.0.0:8088")
HDF5_OUTPUT_DIRECTORY = getenv(
    "DATA_LAYER_API", 
    "/mnt/disk/dev_share/HDF5_from_ZMQ_stream/"
)
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

    def __init__(self, state) -> None:
        """
        Parameters
        ----------
        state : State
            The state of the PrefectWorkflow class. See the State class in
            BlueskyWorkflow for details

        Returns
        -------
        None
        """

        super().__init__()
        self._state = state

        self.prefect_flow_aborted = False
        self.mxcubecore_workflow_aborted = False

        self.robot_client = Client(host=ROBOT_HOST, readonly=False)

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
        pucks = self.robot_client.status.get_loaded_pucks()

        mounted_sample = self.robot_client.status.state.goni_pin
        if mounted_sample is not None:
            for puck in pucks:
                if puck.id == mounted_sample.puck.id:
                    # NOTE: The robot returns the barcode as e.g ASP-3018,
                    # but the data layer expects the format ASP3018
                    return (mounted_sample.id, puck.name.replace("-", ""))

        else:
            raise QueueExecutionException("No pin mounted on the goni", self)
