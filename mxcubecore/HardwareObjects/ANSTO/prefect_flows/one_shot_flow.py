import asyncio
import logging

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from ..Resolution import Resolution
from .abstract_flow import AbstractPrefectWorkflow
from .prefect_client import MX3PrefectClient
from .schemas.one_shot import (
    OneShotDialogBox,
    OneShotParams,
)


class OneShotFlow(AbstractPrefectWorkflow):
    def __init__(self, state, resolution: Resolution):
        super().__init__(state, resolution)

        self._collection_type = "one_shot"

    def run(self, dialog_box_parameters: dict) -> None:
        """Runs the screening flow

        Parameters
        ----------
        dialog_box_parameters : dict
            The parameters obtained from the mxcube dialog box

        Returns
        -------
        None
        """
        # This is the payload we get from the UI
        dialog_box_model = OneShotDialogBox.model_validate(dialog_box_parameters)

        detector_distance = self._resolution_to_distance(
            dialog_box_model.resolution,
            energy=dialog_box_model.photon_energy,
        )

        one_shot_params = OneShotParams(
            omega_range=dialog_box_model.omega_range,
            exposure_time=dialog_box_model.exposure_time,
            number_of_passes=1,
            count_time=None,
            number_of_frames=1,
            detector_distance=detector_distance,
            photon_energy=dialog_box_model.photon_energy,
            beam_size=(80, 80),  # TODO: get beam size,
            # Convert transmission percentage to a value between 0 and 1
            transmission=dialog_box_model.transmission / 100,
        )

        if not settings.ADD_DUMMY_PIN_TO_DB:
            pin = self.get_pin_model_of_mounted_sample_from_db()
            logging.getLogger("HWR").info(f"Mounted pin: {pin}")
            sample_id = pin.id
        else:
            logging.getLogger("HWR").warning(
                "A dummy pin will be added to the database. NOTE that this should "
                "only be used for development"
            )
            sample_id = dialog_box_model.sample_id

        prefect_parameters = {
            "sample_id": sample_id,
            "collection_params": one_shot_params.model_dump(),
            "hardware_trigger": True,
            "add_dummy_pin": settings.ADD_DUMMY_PIN_TO_DB,
        }

        logging.getLogger("HWR").debug(
            f"parameters sent to prefect flow {prefect_parameters}"
        )

        one_shot_flow = MX3PrefectClient(
            name=settings.ONE_SHOT_DEPLOYMENT_NAME, parameters=prefect_parameters
        )

        # Remember the collection params for the next collection
        self._save_dialog_box_params_to_redis(dialog_box_model)

        try:
            loop = self._get_asyncio_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(one_shot_flow.trigger_data_collection(sample_id))
            logging.getLogger("HWR").info("One-shot flow complete")
        except Exception as ex:
            raise QueueExecutionException(str(ex), self) from ex

        self._state.value = "ON"
        self.mxcubecore_workflow_aborted = False

    def dialog_box(self) -> dict:
        """
        Workflow dialog box. Returns a dictionary that follows a JSON schema

        Returns
        -------
        dialog : dict
            A dictionary following the JSON schema.
        """
        properties = {
            "exposure_time": {
                "title": "Total Exposure Time [s]",
                "type": "number",
                "minimum": 0,
                "default": float(self._get_dialog_box_param("exposure_time")),
                "widget": "textarea",
            },
            "omega_range": {
                "title": "Omega Range [degrees]",
                "type": "number",
                "minimum": 0,
                "default": float(self._get_dialog_box_param("omega_range")),
                "widget": "textarea",
            },
            "resolution": {
                "title": "Resolution [Å]",
                "type": "number",
                "minimum": 0,  # TODO: get limits from distance PV
                "maximum": 3000,  # TODO: get limits from distance PV
                "default": float(self._get_dialog_box_param("resolution")),
                "widget": "textarea",
            },
            "transmission": {
                "title": "Transmission [%]",
                "type": "number",
                "minimum": 0,  # TODO: get limits from PV?
                "maximum": 100,
                "default": float(self._get_dialog_box_param("transmission")),
                "widget": "textarea",
            },
        }

        if settings.ADD_DUMMY_PIN_TO_DB:
            properties["sample_id"] = {
                "title": "Database sample id (dev only)",
                "type": "integer",
                "default": 1,
                "widget": "textarea",
            }

        dialog = {
            "properties": properties,
            "required": [
                "exposure_time",
                "omega_range",
                "resolution",
                "transmission",
            ],
            "dialogName": "One Shot Parameters",
        }

        return dialog
