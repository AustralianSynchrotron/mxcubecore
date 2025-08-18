import logging

from mx3_beamline_library.devices.beam import energy_master

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from ..Resolution import Resolution
from .abstract_flow import AbstractPrefectWorkflow
from .schemas.one_shot import (
    OneShotDialogBox,
    OneShotParams,
)
from .sync_prefect_client import MX3SyncPrefectClient


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

        photon_energy = energy_master.get()

        detector_distance = self._resolution_to_distance(
            dialog_box_model.resolution,
            energy=photon_energy,
        )

        one_shot_params = OneShotParams(
            omega_range=dialog_box_model.omega_range,
            exposure_time=dialog_box_model.exposure_time,
            number_of_passes=1,
            count_time=None,
            number_of_frames=1,
            detector_distance=detector_distance,
            photon_energy=photon_energy,
            beam_size=(80, 80),  # TODO: get beam size,
            # Convert transmission percentage to a value between 0 and 1
            transmission=dialog_box_model.transmission / 100,
        )

        if not settings.ADD_DUMMY_PIN_TO_DB:
            logging.getLogger("HWR").info("Getting sample from the data layer...")
            sample_id = self.get_sample_id_of_mounted_sample(
                dialog_box_model.project_name,
                dialog_box_model.lab_name,
                dialog_box_model.sample_name,
            )
            logging.getLogger("HWR").info(f"Mounted sample id: {sample_id}")

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

        one_shot_flow = MX3SyncPrefectClient(
            name=settings.ONE_SHOT_DEPLOYMENT_NAME, parameters=prefect_parameters
        )

        # Remember the collection params for the next collection
        self._save_dialog_box_params_to_redis(dialog_box_model)

        try:
            one_shot_flow.trigger_data_collection(sample_id)
            logging.getLogger("user_level_log").info("One-shot completed successfully.")
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
        resolution_limits = self.resolution.get_limits()

        properties = {
            "exposure_time": {
                "title": "Total Exposure Time [s]",
                "type": "number",
                "exclusiveMinimum": 0,
                "default": float(self._get_dialog_box_param("exposure_time")),
                "widget": "textarea",
            },
            "omega_range": {
                "title": "Omega Range [degrees]",
                "type": "number",
                "exclusiveMinimum": 0,
                "default": float(self._get_dialog_box_param("omega_range")),
                "widget": "textarea",
            },
            "resolution": {
                "title": "Resolution [Å]",
                "type": "number",
                "minimum": resolution_limits[0],
                "maximum": resolution_limits[1],
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

        plate_conditional: dict | None = None
        if self.get_head_type() == "Plate":
            plate_props, plate_conditional = self._build_tray_dialog_schema()
            properties.update(plate_props)

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

        if plate_conditional:
            dialog.update(plate_conditional)

        return dialog
