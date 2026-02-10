from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    PositiveFloat,
    PositiveInt,
    model_validator,
)

from .full_dataset import FullDatasetDialogBox
from .grid_scan import (
    GridScanDialogBox,
    GridScanParams,
)
from .screening import ScreeningDialogBox


class PartialUDCGridScanDialogBox(GridScanDialogBox):
    grid_step: str = Field(
        description="This is set as a string in the UI and is latter mapped to a tuple"
    )


class PartialUDCDialogBox(BaseModel):
    grid_scan: PartialUDCGridScanDialogBox
    run_screening: bool = False
    screening: ScreeningDialogBox | None = None
    run_full_dataset: bool = False
    full_dataset: FullDatasetDialogBox | None = None


# Below are the schemas copied from bluesky_worker single loop data collection flow schema
# Only a subset of the full schema is included here
class OpticalCenteringExtraConfig(BaseModel):
    grid_height_scale_factor: float = 2  # Cut the grid height by this amount


class OpticalCenteringParams(BaseModel):
    beam_position: list[int] | tuple[int, int] = Field(
        default=(612, 512),
        description="Global default. These are pixel (x,y) coordinates",
    )
    grid_step: list[float] | tuple[float, float] = Field(
        default=(80, 80),
        description="Global default. (x,y) grid step measured in micrometers",
    )
    calibrated_alignment_z: float = Field(
        default=0.480,
        description="Calibration parameter. Should be updated regularly",
    )
    extra_config: OpticalCenteringExtraConfig = OpticalCenteringExtraConfig()


class GridScanParams(BaseModel):
    """Parameters for executing grid scans"""

    omega_range: float = Field(description="Global default. Measured in degrees.")
    md3_alignment_y_speed: float = Field(description="Global default. Measured in mm/s")
    detector_distance: float = Field(description="Global default. Measured in meters.")
    photon_energy: float = Field(description="Global default. Measured in keV.")
    transmission: float = Field(strict=True, ge=0, le=1, default=0.1)
    crystal_finder_threshold: int = Field(default=1, description="Global default.")
    detector_roi_mode: Literal["4M", "disabled"]

    number_of_processes: int | None = None


class DataCollectionBase(BaseModel):
    omega_range: float
    exposure_time: PositiveFloat
    number_of_passes: int = 1
    count_time: float | None = None
    degrees_per_frame: float
    detector_distance: PositiveFloat
    photon_energy: PositiveFloat
    transmission: float = Field(strict=True, ge=0, le=1)
    beam_size: tuple[int, int] = (80, 80)


class ScreeningParams(DataCollectionBase):
    """Parameters for collecting screening data"""


class FullDatasetParams(DataCollectionBase):
    """Parameters for collecting full datasets"""

    rotation_axis_offset: int | None = Field(
        default=None,
        description="Output from RadDose. Not yet implemented. Measured in um.",
    )


class ProjectStrategy(BaseModel):
    """Parameters for what to collect on, and when to stop"""

    use_screening: bool = Field(default=True, description="User defined")
    use_dose: bool = Field(
        default=False, description="User defined. Not yet implemented."
    )
    use_rotation_axis_offset: bool = Field(
        default=True, description="User defined. Not yet implemented."
    )

    # Full dataset targets
    target_av_dose: float | None = Field(
        default=None, description="User defined. Not yet implemented. Measured in MGy."
    )
    target_completeness: float | None = Field(
        default=None,
        description="User defined. Measured in percent.",
    )
    target_multiplicity: float | None = Field(
        default=None, description="User defined. Measured in factor."
    )
    target_resolution: float | None = Field(
        default=None, description="User defined. Measured in Å."
    )

    # Screening targets
    screening_target_resolution: float | None = Field(
        default=None,
        description="If None, it is automatically calculated as "
        "target_resolution + 1 [Å] (if target_resolution is not None).",
    )

    # Project criteria
    n_datasets_better_than: int | None = Field(
        default=None, description="User defined."
    )

    @model_validator(mode="before")
    @classmethod
    def set_screening_target_resolution(cls, values: dict):  # noqa
        """if target_resolution is not None, sets the screening target
        resolution to (target_resolution + 1) [Å]
        """
        if values.get("screening_target_resolution") is None:
            if values.get("target_resolution") is not None:
                values["screening_target_resolution"] = values["target_resolution"] + 1
                return values
        return values

    @model_validator(mode="before")
    @classmethod
    def validate_n_datasets_better_than(cls, values: dict):  # noqa
        """
        Checks that at least one target value has been given
        if `n_datasets_better_than` is not None
        """
        keys = [
            "target_av_dose",
            "target_completeness",
            "target_multiplicity",
            "target_resolution",
        ]
        key_vals = []
        if values.get("n_datasets_better_than") is not None:
            for key in keys:
                key_vals.append(values.get(key))
            if not any(key_vals):
                raise ValueError(
                    "n_datasets_better_than has been specified, but no target values "
                    "have been given. Update the ProjectStrategy schema."
                )
            return values
        return values


class ProcessingPipeline(StrEnum):
    DIALS = "dials"
    FAST_DP = "fast_dp"
    DIALS_AND_FAST_DP = "dials_and_fast_dp"
    DOZOR = "dozor"
    FAST_DP_AND_XIA2 = "fast_dp_and_xia2"
    XIA2 = "xia2"


class SingleLoopDataCollectionConfig(BaseModel):
    """Input of the UDC and partial UDC prefect flow"""

    optical_centering: OpticalCenteringParams = OpticalCenteringParams()
    grid_scan: GridScanParams
    screening: ScreeningParams | None = None
    full_dataset: FullDatasetParams | None = None
    project_strategy: ProjectStrategy = ProjectStrategy()
    processing_pipeline: ProcessingPipeline = ProcessingPipeline.FAST_DP

    mount_pin_at_start_of_flow: bool = Field(
        default=True, description="Only must be changed for debugging"
    )
    # Parameters used only for debugging purposes
    add_dummy_pin_to_db: bool = Field(
        default=False, description="Only must be True for debugging"
    )


class ConsistencyError(Exception):
    pass
