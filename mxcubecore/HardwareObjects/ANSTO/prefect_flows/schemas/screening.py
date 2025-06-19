from .common import (
    DataCollectionBase,
    DataCollectionDialogBoxBase,
)


class ScreeningDialogBox(DataCollectionDialogBoxBase):
    crystal_counter: int = 0
    number_of_frames: int


class ScreeningParams(DataCollectionBase):
    """Parameters for collecting screening data"""
