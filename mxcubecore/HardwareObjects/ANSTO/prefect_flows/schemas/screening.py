
from .common import DataCollectionBase, DataCollectionDialogBoxBase


class ScreeningDialogBox(DataCollectionDialogBoxBase):
    processing_pipeline: str = "dials"
    crystal_counter: int = 0
    number_of_frames: int


class ScreeningParams(DataCollectionBase):
    """Parameters for collecting screening data"""
