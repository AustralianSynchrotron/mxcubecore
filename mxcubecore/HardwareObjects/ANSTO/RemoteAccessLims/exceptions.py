__all__ = (
    "RemoteAccessLimsError",
    "SessionNotOpen",
    "IdentityError",
    "UserNotAuthorized",
)


class RemoteAccessLimsError(Exception):
    """Remote Access Lims Error"""


class SessionNotOpen(RemoteAccessLimsError):
    """Session Not Open"""


class IdentityError(RemoteAccessLimsError):
    """Identity Error"""


class UserNotAuthorized(RemoteAccessLimsError):
    """User Not Authorized"""
