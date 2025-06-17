"""
This file contains settings changed via environment variables only
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class PrefectSettings(BaseSettings):
    PREFECT_URI: str = Field("http://localhost:4200", env="PREFECT_URI")
    ONE_SHOT_DEPLOYMENT_NAME: str = Field(
        "mxcube-one-shot/plans", env="ONE_SHOT_DEPLOYMENT_NAME"
    )
    GRID_SCAN_DEPLOYMENT_NAME: str = Field(
        "mxcube-grid-scan/plans", env="GRID_SCAN_DEPLOYMENT_NAME"
    )
    GRID_SCAN_NUMBER_OF_PROCESSES: int | None = Field(
        None,
        env="GRID_SCAN_NUMBER_OF_PROCESSES",
        description="Number of processes used to process grid scan frames",
    )

    FULL_DATASET_DEPLOYMENT_NAME: str = Field(
        "mxcube-full-data-collection/plans", env="FULL_DATASET_DEPLOYMENT_NAME"
    )

    SCREENING_DEPLOYMENT_NAME: str = Field(
        "mxcube-screening/plans", env="SCREENING_DEPLOYMENT_NAME"
    )
    SAMPLE_CENTERING_PREFECT_DEPLOYMENT_NAME: str = Field(
        "mxcube-sample-centering/plans", env="SAMPLE_CENTERING_PREFECT_DEPLOYMENT_NAME"
    )
    USE_TOP_CAMERA: bool = Field(
        True, env="USE_TOP_CAMERA", description="False only for development"
    )
    CALIBRATED_ALIGNMENT_Z: float = Field(0.487, env="CALIBRATED_ALIGNMENT_Z")


class MD3(BaseSettings):
    MD3_REDIS_HOST: str = Field("127.0.0.0", env="MD3_REDIS_HOST")
    MD3_REDIS_PORT: int = Field("6379", env="MD3_REDIS_PORT")
    EXPORTER_ADDRESS: str = Field("127.0.0.0:1234", env="EXPORTER_ADDRESS")


class RedisSettings(BaseSettings):
    MXCUBE_REDIS_HOST: str = Field("localhost", env="MXCUBE_REDIS_HOST")
    MXCUBE_REDIS_PORT: int = Field("6379", env="MXCUBE_REDIS_PORT")
    MXCUBE_REDIS_USERNAME: str | None = Field(None, env="MXCUBE_REDIS_USERNAME")
    MXCUBE_REDIS_PASSWORD: str | None = Field(None, env="MXCUBE_REDIS_PASSWORD")
    MXCUBE_REDIS_DB: int = Field(0, env="MXCUBE_REDIS_DB")


class Robot(BaseSettings):
    ROBOT_HOST: str = Field(default="127.0.0.0", env="ROBOT_HOST")


class APIs(BaseSettings):
    DATA_LAYER_API: str = Field(default="http://0.0.0.0:8088", env="DATA_LAYER_API")
    SIMPLON_API: str = Field(default="http://0.0.0.0:8000", env="SIMPLON_API")


class ANSTOConfig(APIs, Robot, RedisSettings, MD3, PrefectSettings):
    BL_ACTIVE: bool = Field(default=False, env="BL_ACTIVE")
    ADD_DUMMY_PIN_TO_DB: bool = Field(
        default=False,
        env="ADD_DUMMY_PIN_TO_DB",
        description="True only for development",
    )


settings = ANSTOConfig()
print(settings)
