import logging

from mx3_beamline_library.devices.beam import energy_master

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from ..redis_utils import get_redis_connection
from ..Resolution import Resolution
from .abstract_flow import AbstractPrefectWorkflow
from .schemas.partial_udc import (
    GridScanParams,
    OpticalCenteringExtraConfig,
    OpticalCenteringParams,
    PartialUDCDialogBox,
    ScreeningParams,
    SingleLoopDataCollectionConfig,
)
from .sync_prefect_client import MX3SyncPrefectClient


class PartialUDCFlow(AbstractPrefectWorkflow):
    """Prefect Raster Workflow"""

    def __init__(
        self,
        state,
        resolution: Resolution,
        sample_id: int | None,
    ) -> None:
        super().__init__(state, resolution, sample_id=sample_id)

        self._collection_type = "partial_udc"
        self.grid_step_map = {
            "5x5": (5.0, 5.0),
            "10x10": (10.0, 10.0),
            "20x20": (20.0, 20.0),
        }

    def run(self, dialog_box_parameters: dict) -> None:
        """


        Parameters
        ----------
        dialog_box_parameters : dict
            A dictionary containing parameters from the dialog box

        Returns
        -------
        None
        """

        self._state.value = "RUNNING"

        dialog_box_model = PartialUDCDialogBox.model_validate(dialog_box_parameters)
        head_type = self.get_head_type()

        grid_scan_model = dialog_box_model.grid_scan
        screening_model = dialog_box_model.screening

        if not settings.ADD_DUMMY_PIN_TO_DB:
            if self.sample_id is None:
                logging.getLogger("HWR").info("Getting sample from the data layer...")
                sample_id = self.get_sample_id_of_mounted_sample(grid_scan_model)
                logging.getLogger("HWR").info(f"Mounted sample id: {sample_id}")
            else:
                logging.getLogger("HWR").info(
                    f"Hand-mount mode, sample id: {self.sample_id}"
                )
                sample_id = self.sample_id

        else:
            logging.getLogger("HWR").warning(
                "SIM mode! The sample id will not be obtained from the data layer. "
                "Setting sample id to 1. "
                "Ensure that this sample id exists in the db before launching the flow"
            )
            sample_id = 1

        photon_energy = energy_master.get()

        with get_redis_connection() as redis_connection:
            default_resolution = float(redis_connection.get("grid_scan:resolution"))

        detector_distance = self._resolution_to_distance(
            default_resolution,
            energy=photon_energy,
        )
        logging.getLogger("HWR").info(
            f"Detector distance corresponding to {default_resolution} A: {detector_distance} [m]"
        )

        # TODO: partial udc for plates not supported yet
        if head_type == "Plate":
            use_centring_table = False
            msg = "Partial UDC for plates is not supported yet"
            logging.getLogger("user_level_log").error(msg)
            raise QueueExecutionException(msg, self)
        else:
            use_centring_table = True

        partial_udc_config = SingleLoopDataCollectionConfig(
            optical_centering=OpticalCenteringParams(
                beam_position=(612, 512),
                extra_config=OpticalCenteringExtraConfig(grid_height_scale_factor=2),
                grid_step=self.grid_step_map[grid_scan_model.grid_step],
                calibrated_alignment_z=0.85,  # TODO: maybe get from redis?
            ),
            grid_scan=GridScanParams(
                omega_range=0,
                md3_alignment_y_speed=grid_scan_model.md3_alignment_y_speed,
                detector_distance=detector_distance,
                photon_energy=photon_energy,
                transmission=grid_scan_model.transmission / 100,
                crystal_finder_threshold=1,  # TODO: can user set this?
                number_of_processes=settings.GRID_SCAN_NUMBER_OF_PROCESSES,
            ),
            screening=ScreeningParams(
                omega_range=screening_model.omega_range,
                exposure_time=screening_model.exposure_time,
                number_of_passes=1,
                count_time=None,
                number_of_frames=screening_model.number_of_frames,
                detector_distance=self._resolution_to_distance(
                    screening_model.resolution,
                    energy=photon_energy,
                ),
                photon_energy=photon_energy,
                transmission=screening_model.transmission / 100,
                beam_size=(80, 80),
            ),
            full_dataset=None,
            mount_pin_at_start_of_flow=False,
            add_dummy_pin_to_db=settings.ADD_DUMMY_PIN_TO_DB,
        )
        prefect_parameters = {
            "sample_id": sample_id,
            "pin": None,
            "prepick_pin": None,
            "config": partial_udc_config.model_dump(exclude_none=True),
        }

        logging.getLogger("HWR").info(
            f"Parameters sent to prefect flow: {prefect_parameters}"
        )

        # Remember the collection params for the next collection
        self._save_dialog_box_params_to_redis(grid_scan_model, collection_type="grid_scan")
        self._save_dialog_box_params_to_redis(screening_model, collection_type="screening")
        partial_udc_flow = MX3SyncPrefectClient(
            name=settings.PARTIAL_UDC_DEPLOYMENT_NAME, parameters=prefect_parameters
        )
        try:
            partial_udc_flow.trigger_data_collection(sample_id, mode="partial_udc")
            logging.getLogger("user_level_log").info(
                "Partial UDC completed successfully."
            )
            self._state.value = "ON"
            self.mxcubecore_workflow_aborted = False
        except Exception as ex:
            raise QueueExecutionException(str(ex), self) from ex

    def dialog_box(self) -> dict:
        """
        Workflow dialog box. Returns a dictionary that follows a JSON schema

        Returns
        -------
        dialog : dict
            A dictionary following the JSON schema.
        """
        # Grid Scan Properties
        gs_properties = {
            "md3_alignment_y_speed": {
                "title": "Alignment Y Speed [mm/s]",
                "type": "number",
                "minimum": 0.1,
                "maximum": 14.8,
                "default": float(
                    self._get_dialog_box_param(
                        "md3_alignment_y_speed", collection_type="grid_scan"
                    )
                ),
                "widget": "textarea",
            },
            "transmission": {
                "title": "Transmission [%]",
                "type": "number",
                "minimum": 0,
                "maximum": 100,
                "default": float(
                    self._get_dialog_box_param(
                        "transmission", collection_type="grid_scan"
                    )
                ),
                "widget": "textarea",
            },
            "detector_roi_mode": {
                "title": "Detector ROI Mode",
                "type": "string",
                "enum": ["4M", "disabled"],
                "default": str(
                    self._get_dialog_box_param(
                        "detector_roi_mode", collection_type="grid_scan"
                    )
                ),
                "widget": "select",
            },
            "grid_step": {
                "title": "Grid Step [um]",
                "type": "string",
                "enum": ["5x5", "10x10", "20x20"],
                "default": str(
                    self._get_dialog_box_param("grid_step", collection_type="grid_scan")
                ),
                "widget": "select",
            },
        }

        tray_conditional: dict | None = None
        if self.get_head_type() == "Plate":
            tray_properties, tray_conditional = self.build_tray_dialog_schema()
            gs_properties.update(tray_properties)

        # Screening Properties
        resolution_limits = self.resolution.get_limits()
        sc_properties = {
            "exposure_time": {
                "title": "Total Exposure Time [s]",
                "type": "number",
                "exclusiveMinimum": 0,
                "default": float(
                    self._get_dialog_box_param(
                        "exposure_time", collection_type="screening"
                    )
                ),
                "widget": "textarea",
            },
            "omega_range": {
                "title": "Omega Range [degrees]",
                "type": "number",
                "exclusiveMinimum": 0,
                "default": float(
                    self._get_dialog_box_param(
                        "omega_range", collection_type="screening"
                    )
                ),
                "widget": "textarea",
            },
            "number_of_frames": {
                "title": "Number of Frames",
                "type": "integer",
                "minimum": 1,
                "default": int(
                    self._get_dialog_box_param(
                        "number_of_frames", collection_type="screening"
                    )
                ),
                "widget": "textarea",
            },
            "resolution": {
                "title": "Resolution [Å]",
                "type": "number",
                "minimum": resolution_limits[0],
                "maximum": resolution_limits[1],
                "default": float(
                    self._get_dialog_box_param(
                        "resolution", collection_type="screening"
                    )
                ),
                "widget": "textarea",
            },
            "transmission": {
                "title": "Transmission [%]",
                "type": "number",
                "minimum": 0,
                "maximum": 100,
                "default": float(
                    self._get_dialog_box_param(
                        "transmission", collection_type="screening"
                    )
                ),
                "widget": "textarea",
            },
            "crystal_counter": {
                "title": "Crystal ID",
                "type": "integer",
                "minimum": 0,
                "default": int(
                    self._get_dialog_box_param(
                        "crystal_counter", collection_type="screening"
                    )
                ),
                "widget": "textarea",
            },
        }

        if settings.ADD_DUMMY_PIN_TO_DB:
            # Dev only
            sc_properties["sample_id"] = {
                "title": "Database sample id (dev only)",
                "type": "integer",
                "default": 1,
                "widget": "textarea",
            }

        dialog = {
            "properties": {
                "grid_scan": {
                    "type": "object",
                    "title": "Grid Scan Parameters",
                    "properties": gs_properties,
                    "required": [
                        "md3_alignment_y_speed",
                        "transmission",
                    ],
                },
                "screening": {
                    "type": "object",
                    "title": "Screening Parameters",
                    "properties": sc_properties,
                    "required": [
                        "exposure_time",
                        "omega_range",
                        "number_of_frames",
                        "resolution",
                        "crystal_counter",
                        "transmission",
                    ],
                },
            },
            "required": ["grid_scan", "screening"],
            "dialogName": "Partial UDC Parameters",
        }

        if tray_conditional:
            dialog["properties"]["grid_scan"].update(tray_conditional)

        return dialog
