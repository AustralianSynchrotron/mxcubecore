from typing_extensions import Literal, TypedDict
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, UUID4, with_config


@with_config(ConfigDict(extra="allow"))
class KeycloakUserInfo(TypedDict, total=True):
    """Keycloak User Info"""

    identity_uuid: UUID4
    preferred_username: str


@with_config(ConfigDict(extra="allow"))
class KeycloakInfo(TypedDict, total=True):
    """Keycloak Info"""

    userinfo: KeycloakUserInfo


class RemoteAccessSession(BaseModel):
    """Open Session Read"""

    id: UUID4 = Field(
        title="ID",
    )
    name: str = Field(
        title="Name",
    )
    start: datetime = Field(
        title="Start",
    )
    end: datetime = Field(
        title="End",
    )
    opened_at: datetime = Field(
        title="Opened At",
    )
    state: Literal["open"] = Field(
        title="State",
        examples=["open"],
    )
    epn: str = Field(
        title="EPN",
        description="Experimental Proposal Number",
    )
    primary_user_id: UUID4 = Field(
        title="Primary User",
        description=(
            "User who will be in primary control of experimental hardware."
            "\n This can either be a staff member or a user "
            "participating in the experiment."
        ),
    )
    users: list[UUID4] = Field(
        title="Users",
    )
    staff: list[UUID4] = Field(
        title="Staff",
    )
