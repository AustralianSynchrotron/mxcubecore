from datetime import datetime

from pydantic import (
    BaseModel,
    Field,
)


class TimeStampMixin(BaseModel):
    """Timestamp Mixin"""

    created_at: datetime = Field(
        title="Create Date",
        description="Date entry created.",
    )
    updated_at: datetime = Field(
        title="Write Date",
        description="Date entry updated.",
    )


class PinRead(TimeStampMixin, BaseModel):
    """Abstract Pin Schema"""

    id: int
    port: int
    type: str
    notes: str
    description: str
    name: str
