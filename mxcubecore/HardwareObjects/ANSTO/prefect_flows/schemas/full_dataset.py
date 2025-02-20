from typing import (
    Optional,
    Union,
)

from pydantic.v1 import (
    BaseModel,
    Field,
)


class FullDatasetDialogBox(BaseModel):
    exposure_time: float
    omega_range: float
    number_of_frames: int
    detector_distance: float
    photon_energy: float
    hardware_trigger: bool = True
    sample_id: Optional[str] = None
    processing_pipeline: str = "dials"
    crystal_counter: int = 0


class FullDatasetParams(BaseModel):
    """Parameters for collecting full datasets"""

    start_omega: float = Field(
        default=0, description="Output from XPLAN. Measured in degrees."
    )
    omega_range: float = Field(
        default=10, description="Output from XPLAN. Measured in degrees."
    )
    exposure_time: float = Field(
        default=1, description="Output from RadDose. Measured in seconds."
    )
    number_of_passes: int = 1
    count_time: float = None
    number_of_frames: int = Field(
        default=100,
        description="Global default. Determined by the detector frame rate and exposure time.",
    )
    detector_distance: float = Field(
        default=-0.298, description="Output from XPLAN. Measured in m."
    )
    photon_energy: float = Field(
        default=12700, description="Global default. Measured in eV."
    )
    beam_size: Union[tuple[int, int], list[int]] = Field(
        default=(80, 80),
        description="Determined by the crystal finder. Not currently used. "
        "Measured in um.",
    )

    rotation_axis_offset: Union[int, None] = Field(
        default=None,
        description="Output from RadDose. Not yet implemented. Measured in um.",
    )
    # TODO: add pydozor_config ?

    class Config:
        extra = "forbid"
