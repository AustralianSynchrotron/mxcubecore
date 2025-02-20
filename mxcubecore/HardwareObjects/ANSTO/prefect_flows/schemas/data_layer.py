from pydantic import BaseModel, Field
from datetime import datetime

class TimeStampMixin(BaseModel):
    """Timestamp Mixin"""

    createDate: datetime = Field(
        title="Create Date",
        description="Date entry created.",
    )
    writeDate: datetime = Field(
        title="Write Date",
        description="Date entry updated.",
    )

class PinRead(TimeStampMixin, BaseModel):
    """Abstract Pin Schema"""
    id: int = Field(title="Pin ID", examples=[1])
    puckId: int = Field(title="Puck ID", examples=[1])
    port: int = Field(title="Pin ID", examples=[3])
    projectId: int = Field(title="Project ID", examples=[1])
    sampleName: str = Field(title="Sample Name", examples=["SpiderSilk_1"])
    crystals: list[int] | None = Field(title="Crystals", examples=[[1]], default=None)