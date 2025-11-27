from .utils import get_dialog_box_param


def get_screening_schema(resolution_limits: tuple[float, float]) -> dict:
    properties = {
        "exposure_time": {
            "title": "Total Exposure Time [s]",
            "type": "number",
            "exclusiveMinimum": 0,
            "default": float(
                get_dialog_box_param("exposure_time", collection_type="screening")
            ),
            "widget": "textarea",
        },
        "omega_range": {
            "title": "Omega Range [degrees]",
            "type": "number",
            "exclusiveMinimum": 0,
            "default": float(
                get_dialog_box_param("omega_range", collection_type="screening")
            ),
            "widget": "textarea",
        },
        "number_of_frames": {
            "title": "Number of Frames",
            "type": "integer",
            "minimum": 1,
            "default": int(
                get_dialog_box_param("number_of_frames", collection_type="screening")
            ),
            "widget": "textarea",
        },
        "resolution": {
            "title": "Resolution [Å]",
            "type": "number",
            "minimum": resolution_limits[0],
            "maximum": resolution_limits[1],
            "default": float(
                get_dialog_box_param("resolution", collection_type="screening")
            ),
            "widget": "textarea",
        },
        "transmission": {
            "title": "Transmission [%]",
            "type": "number",
            "minimum": 0,
            "maximum": 100,
            "default": float(
                get_dialog_box_param("transmission", collection_type="screening")
            ),
            "widget": "textarea",
        },
        "crystal_counter": {
            "title": "Crystal ID",
            "type": "integer",
            "minimum": 0,
            "default": int(
                get_dialog_box_param("crystal_counter", collection_type="screening")
            ),
            "widget": "textarea",
        },
    }
    return properties
