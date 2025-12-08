from .common import (
    DataCollectionBase,
    DataCollectionDialogBoxBase,
)


class ScreeningDialogBox(DataCollectionDialogBoxBase):
    crystal_counter: int = 0
    degrees_per_frame: float


class ScreeningParams(DataCollectionBase):
    """Parameters for collecting screening data"""
