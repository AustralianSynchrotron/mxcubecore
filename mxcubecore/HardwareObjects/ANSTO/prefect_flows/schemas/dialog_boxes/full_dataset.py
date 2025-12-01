from .utils import get_dialog_box_param


def get_full_dataset_schema(
    resolution_limits: tuple[float, float], partial_udc: bool = False
) -> dict:
    properties = {
        "exposure_time": {
            "title": "Total Exposure Time [s]",
            "type": "number",
            "exclusiveMinimum": 0,
            "default": float(
                get_dialog_box_param("exposure_time", collection_type="full_dataset")
            ),
            "widget": "textarea",
        },
        "omega_range": {
            "title": "Omega Range [degrees]",
            "type": "number",
            "exclusiveMinimum": 0,
            "default": float(
                get_dialog_box_param("omega_range", collection_type="full_dataset")
            ),
            "widget": "textarea",
        },
        "number_of_frames": {
            "title": "Number of Frames",
            "type": "integer",
            "minimum": 1,
            "default": int(
                get_dialog_box_param("number_of_frames", collection_type="full_dataset")
            ),
            "widget": "textarea",
        },
        "resolution": {
            "title": "Resolution [Å]",
            "type": "number",
            "minimum": resolution_limits[0],
            "maximum": resolution_limits[1],
            "default": float(
                get_dialog_box_param("resolution", collection_type="full_dataset")
            ),
            "widget": "textarea",
        },
        "transmission": {
            "title": "Transmission [%]",
            "type": "number",
            "minimum": 0,
            "maximum": 100,
            "default": float(
                get_dialog_box_param("transmission", collection_type="full_dataset")
            ),
            "widget": "textarea",
        },
        "processing_pipeline": {
            "title": "Data Processing Pipeline",
            "type": "string",
            "enum": [
                "dials",
                "fast_dp",
                "dials_and_fast_dp",
                "fast_dp_and_xia2",
                "xia2",
            ],
            "default": get_dialog_box_param(
                "processing_pipeline", collection_type="full_dataset"
            ),
        },
    }
    if not partial_udc:
        properties["crystal_counter"] = {
            "title": "Crystal ID",
            "type": "integer",
            "minimum": 0,
            "default": int(
                get_dialog_box_param("crystal_counter", collection_type="full_dataset")
            ),
            "widget": "textarea",
        }
    return properties
