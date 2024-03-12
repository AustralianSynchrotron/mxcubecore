from pydantic import Field, BaseModel
from typing import Union

class ScreeningParams(BaseModel):
    """Parameters for collecting screening data"""

    start_omega: float = Field(
        default=0,
        description="Output from loop centering (flat angle). Measured in degrees.",
    )
    omega_range: float = Field(
        default=10, description="Global default. Measured in degrees."
    )
    exposure_time: float = Field(
        default=1, description="Global default. Measured in seconds."
    )
    number_of_passes: int = 1
    count_time: float = None
    number_of_frames: int = Field(
        default=100,
        description="Global default. Determined by the detector frame rate and exposure time.",
    )
    detector_distance: float = Field(default=-0.298, description="Output from Dozor")
    photon_energy: float = Field(
        default=12700, description="Global default. Measured in eV."
    )
    beam_size: Union[tuple[int, int], list[int]] = Field(
        default=(80, 80),
        description="Determined by the crystal finder. Not currently used. "
        "Measured in um.",
    )
    class Config:
        extra = "forbid"


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

    rotation_axis_offset: Union[int,None] = Field(
        default=None,
        description="Output from RadDose. Not yet implemented. Measured in um.",
    )
    class Config:
        extra = "forbid"
