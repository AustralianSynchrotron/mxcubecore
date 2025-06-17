from pydantic import (
    Field,
)
from .common import DataCollectionBase, DataCollectionDialogBoxBase


# NOTE: The detector_distance and energy units used in
# the FullDatasetDialogBox and Prefect FullDatasetParams are different
# on purpose
class FullDatasetDialogBox(DataCollectionDialogBoxBase):
    processing_pipeline: str = "dials"
    crystal_counter: int = 0
    number_of_frames: int



class FullDatasetParams(DataCollectionBase):
    """Parameters for collecting full datasets"""
    rotation_axis_offset: int | None = Field(
        default=None,
        description="Output from RadDose. Not yet implemented. Measured in um.",
    )
    # TODO: add pydozor_config ?

    class Config:
        extra = "forbid"
