from enum import Enum

class PrefectFlows(str, Enum):
    screen_sample = "Screen Sample"
    collect_dataset = "Collect Dataset"
    grid_scan = "Grid Scan"
