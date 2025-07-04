from datetime import timezone
from inspect import stack as inspect_stack
from typing import (
    Any,
    cast,
)
from urllib.parse import urljoin

from dateutil.tz import gettz
from flask import request
from gevent import sleep as gevent_sleep
from httpx import Response as HttpxResponse
from httpx import get as httpx_get
from mxcubeweb.app import MXCUBEApplication
from mxcubeweb.core.components.user.database import UserDatastore
from mxcubeweb.core.models.usermodels import User
from pydantic import (
    AnyHttpUrl,
    TypeAdapter,
)
from pydantic_core import (
    Url,
    ValidationError,
)
from typing_extensions import Literal

from mxcubecore.HardwareObjects.abstract.AbstractLims import AbstractLims
from mxcubecore.model.lims_session import (
    Lims,
    LimsSessionManager,
    Session,
)
from mxcubecore.TaskUtils import task as dtask

from .exceptions import (
    IdentityError,
    SessionNotOpen,
    UserNotAuthorized,
)
from .schemas import (
    KeycloakInfo,
    RemoteAccessSession,
)


class RemoteAccessLims(AbstractLims):
    """Remote Access Lims"""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def init(self) -> None:
        super().init()
        self._beamline_name = self.get_property("beamline_name")
        self._beamline_description = self.get_property("beamline_description", "")
        self._beamline_details = [
            Lims(
                name=self._beamline_name,
                description=self._beamline_description,
            ),
        ]
        _gateway_api_url = cast(
            Url,
            TypeAdapter(
                AnyHttpUrl,
            ).validate_python(
                self.get_property("gateway_api_url"),
            ),
        )
        self._gateway_api_url = str(_gateway_api_url)
        self._local_timezone = gettz(self.get_property("local_timezone", None))

        # Start Remote Access Polling
        self.__remote_access_polling_task(wait=False)

    @dtask
    def __remote_access_polling_task(self, *args: Any, **kwargs: Any) -> None:
        """Remote Access Polling Task"""
        while True:
            gevent_sleep(1)
            try:
                _user_datastore = cast(
                    UserDatastore,
                    MXCUBEApplication.server.user_datastore,
                )
                _remote_access_session = self._get_remote_access_session()

                if _remote_access_session is None:
                    # Remote Access closed, force signout all sessions
                    _db_users = cast(
                        list[User],
                        _user_datastore.user_model.query.all(),
                    )
                    for _db_user in _db_users:
                        _socketio_sid = _db_user.socketio_session_id
                        _user_datastore.delete_user(_db_user)
                        _user_datastore.commit()
                        MXCUBEApplication.server.emit(
                            "forceSignout",
                            room=_socketio_sid,
                            namespace="/hwr",
                        )

                if _remote_access_session is not None:
                    # Remote Access opened
                    _db_primary_user = cast(
                        User | None,
                        MXCUBEApplication.usermanager.get_operator(),
                    )
                    _primary_user_id = _remote_access_session.primary_user_id
                    if _db_primary_user is None:
                        # No operator / primary user defined
                        _db_users = cast(
                            list[User],
                            _user_datastore.user_model.query.all(),
                        )
                        for _db_user in _db_users:
                            if _db_user.username == str(_primary_user_id):
                                _db_user.in_control = True
                                _user_datastore.put(_db_user)
                                _user_datastore.commit()
                                MXCUBEApplication.server.emit(
                                    "userChanged",
                                    "You were given control",
                                    room=_db_user.socketio_session_id,
                                    namespace="/hwr",
                                )
                                MXCUBEApplication.server.emit(
                                    "observersChanged",
                                    namespace="/hwr",
                                )
                                break
                    elif _db_primary_user.username != str(_primary_user_id):
                        # The operator / primary user needs to be updated
                        _db_primary_user.in_control = False
                        _user_datastore.put(_db_user)
                        _user_datastore.commit()

                        _db_users = cast(
                            list[User],
                            _user_datastore.user_model.query.all(),
                        )
                        for _db_user in _db_users:
                            if _db_user.username == str(_primary_user_id):
                                _db_user.in_control = True
                                _user_datastore.put(_db_user)
                                _user_datastore.commit()
                                MXCUBEApplication.server.emit(
                                    "userChanged",
                                    room=_db_primary_user.socketio_session_id,
                                    namespace="/hwr",
                                )
                                MXCUBEApplication.server.emit(
                                    "userChanged",
                                    "You were given control",
                                    room=_db_user.socketio_session_id,
                                    namespace="/hwr",
                                )
                                MXCUBEApplication.server.emit(
                                    "observersChanged",
                                    namespace="/hwr",
                                )
                                break

                    _all_remote_access_users: list[str] = []
                    for _user_id in _remote_access_session.users:
                        if str(_user_id) not in _all_remote_access_users:
                            _all_remote_access_users.append(str(_user_id))
                    for _staff_id in _remote_access_session.staff:
                        if str(_staff_id) not in _all_remote_access_users:
                            _all_remote_access_users.append(str(_staff_id))

                    _db_users = cast(
                        list[User],
                        _user_datastore.user_model.query.all(),
                    )
                    for _db_user in _db_users:
                        if _db_user.username not in _all_remote_access_users:
                            # User has been removed from session, force signout
                            _socketio_sid = _db_user.socketio_session_id
                            _user_datastore.delete_user(_db_user)
                            _user_datastore.commit()
                            MXCUBEApplication.server.emit(
                                "forceSignout",
                                room=_socketio_sid,
                                namespace="/hwr",
                            )
            except Exception:
                pass

    def _get_keycloak_info(self) -> KeycloakInfo:
        """Retrieves Keycloak information including the relevant access token,
        identity token, and decoded JWT user details.

        Returns
        -------
        KeycloakInfo
            Keycloak information.

        Raises
        ------
        IdentityError
            If identity could not be retrieved.
        """
        # This is an Ugly hack to get Keycloak information stored in the JWT.
        # MXCuBE-Web doesn't pass the decoded JWT down the stack to the LIMS layer.
        # The way we get around this is by traversing back up the stack to read
        # this information from the local variables of method which does have it.

        # Currently there are two methods which contain the information we need:
        # mxcubeweb/core/components/user/usermanager.py#L190
        # And:
        # mxcubeweb/core/components/user/usermanager.py#L319
        _sso_info: dict[str, Any] | None = None
        for _item in inspect_stack():
            _frame = _item[0]
            if "sso_data" in _frame.f_locals:
                _sso_info = _frame.f_locals["sso_data"]
                break

        _keycloak_info: KeycloakInfo
        try:
            _keycloak_info = TypeAdapter(KeycloakInfo).validate_python(_sso_info)
        except ValidationError as ex:
            raise IdentityError("Identity could not be retrieved.") from ex
        return _keycloak_info

    def _get_remote_access_session(self) -> RemoteAccessSession | None:
        """Retrieve remote access session information.

        Returns
        -------
        RemoteAccessSession | None
            Remote access session if open or `None` if closed.
        """
        _res: HttpxResponse
        _res = httpx_get(
            url=urljoin(self._gateway_api_url, "session/open"),
            headers={"accept": "application/json"},
            timeout=5.0,
        )
        if _res.status_code != 200:
            return None

        _session: RemoteAccessSession | None
        try:
            _session = RemoteAccessSession.model_validate_json(_res.content)
        except ValidationError:
            _session = None
        return _session

    def get_lims_name(self) -> list[Lims]:
        """Returns the LIMS used, name and description.

        Returns
        -------
        list[Lims]
            List of LIMS.
        """
        return self._beamline_details

    def get_user_name(self) -> str:
        """Returns the user name of the current user.

        For the purposes of integrating with the Remote Access this method
        returns the Identity API UUID of the user.

        Returns
        -------
        str
            Identity UUID.
        """
        _keycloak_info = self._get_keycloak_info()
        return str(_keycloak_info["userinfo"]["identity_uuid"])

    def get_full_user_name(self) -> str:
        """
        Returns the user name of the current user
        """
        _keycloak_info = self._get_keycloak_info()
        return _keycloak_info["userinfo"]["preferred_username"]

    def login(self, *args: Any, **kwargs: Any) -> list[Session]:
        """Login to LIMS.

        Returns
        -------
        list[Session]
            List of LIMS sessions.

        Raises
        ------
        SessionNotOpen
            If remote access session is not open.
        UserNotAuthorized
            If user is not authorized for remote access session.
        """
        _remote_access_session = self._get_remote_access_session()

        if _remote_access_session is None:
            raise SessionNotOpen("Remote Access Session Not Open.")

        _keycloak_info = self._get_keycloak_info()
        _identity_uuid = _keycloak_info["userinfo"]["identity_uuid"]

        if _identity_uuid not in _remote_access_session.users:
            if _identity_uuid not in _remote_access_session.staff:
                raise UserNotAuthorized("User not authorized to access this session.")

        _start_datetime = _remote_access_session.start.replace(tzinfo=timezone.utc)
        _end_datetime = _remote_access_session.end.replace(tzinfo=timezone.utc)
        _start_datetime_local = _start_datetime.astimezone(self._local_timezone)
        _end_datetime_local = _end_datetime.astimezone(self._local_timezone)

        _session: Session = Session.validate(
            {
                "session_id": str(_remote_access_session.id),
                "beamline_name": self.beamline_name,
                "start_date": _start_datetime_local.strftime("%Y%m%d"),
                "start_time": _start_datetime_local.strftime("%H:%M:%S"),
                "end_date": _end_datetime_local.strftime("%Y%m%d"),
                "end_time": _end_datetime_local.strftime("%H:%M:%S"),
                "title": _remote_access_session.name,
                "code": _remote_access_session.epn,
                "number": "",
                "proposal_id": _remote_access_session.epn,
                "proposal_name": _remote_access_session.epn,
                "comments": "",
                "nb_shifts": "",
                "scheduled": "True",
                "is_rescheduled": False,
                "is_scheduled_time": True,
                "is_scheduled_beamline": True,
                "user_portal_URL": "",
                "data_portal_URL": "",
                "logbook_URL": "",
            }
        )
        self.session_manager = LimsSessionManager(
            sessions=[_session], active_session=_session
        )
        return self.session_manager

    def is_user_login_type(self) -> Literal[True]:
        """Returns True if the login type is user based (not done with proposal).

        Returns
        -------
        Literal[True]
            Always returns `True`.
        """
        return True

    def echo(self) -> Literal[True]:
        """Returns True of LIMS is responding.

        Returns
        -------
        Literal[True]
            Always returns `True`.
        """
        return True

    def get_proposals_by_user(self, login_id: str) -> list[dict]:
        """
        Returns a list with proposal dictionaries for login_id

        Proposal dictioanry strucutre:
            {
                "Proposal": proposal,
                "Person": ,
                "Laboratory":,
                "Session":,
            }

        """
        raise NotImplementedError()

    def create_session(self, proposal_tuple: LimsSessionManager) -> LimsSessionManager:
        """
        TBD
        """
        raise NotImplementedError()

    def get_samples(self, lims_name: str) -> list[dict]:
        """
        Returns a list of sample dictionaires for the current user from lims_name

        Structure of sample dictionary:
        {
            "containerCode": str,
            "containerSampleChangerLocation": int,
            "crystalId": int,
            "crystalSpaceGroup": str,
            "diffractionPlan": {
                "diffractionPlanId": int
             },
            "proteinAcronym": "str,
            "sampleId": int,
            "sampleLocation": int,
            "sampleName": str
        }
        """
        raise NotImplementedError()

    def store_robot_action(self, robot_action_dict: dict):
        """
        Stores the robot action dictionary.

        Structure of robot_action_dictionary:
        {
            "actionType":str,
            "containerLocation": str,
            "dewarLocation":str,
            "message":str,
            "sampleBarcode":str,
            "sessionId":int,
            "sampleId":int.
            "startTime":str,
            "endTime":str,
            "xtalSnapshotAfter:str",
            "xtalSnapshotBefore:str",
        }

        Args:
            robot_action_dict: robot action dictionary as defined above
        """
        raise NotImplementedError()

    def store_beamline_setup(self, session_id: str, bl_config_dict: dict) -> int:
        """
        Stores the beamline setup dict bl_config_dict for session_id

        Args:
            session_id: The session id that the beamline_setup should be
                        associated with.

            bl_config_dict: The dictonary with beamline settings.

        Returns:
            The id of the beamline setup.
        """
        raise NotImplementedError()

    def store_image(self, image_dict: dict) -> None:
        """
        Stores (image parameters) <image_dict>

        Args:
            image_dict: A dictonary with image pramaters.
        """
        raise NotImplementedError()

    def store_energy_scan(self, energyscan_dict: dict) -> None:
        """
        Store energyscan data

        Args:
            energyscan_dict: Energyscan data to store.

        Returns:
            Dictonary with the energy scan id {"energyScanId": int}
        """
        raise NotImplementedError()

    def store_xfe_spectrum(self, xfespectrum_dict: dict):
        """
        Stores a XFE spectrum.

        Args:
            xfespectrum_dict: XFE scan data to store.

        Returns:
            Dictonary with the XFE scan id {"xfeFluorescenceSpectrumId": int}
        """
        raise NotImplementedError()

    def store_workflow(self, workflow_dict: dict) -> tuple[int, int, int]:
        """
        Stores worklflow data workflow_dict

        Structure of workflow_dict:
        {
            "workflow_id": int,
            "workflow_type": str,
            "comments": str,
            "log_file_path": str,
            "result_file_path": str,
            "status": str,
            "title": str,
            "grid_info_id": int,
            "dx_mm": float,
            "dy_mm": float,
            "mesh_angle": float,
            "steps_x": float,
            "steps_y": float,
            "xOffset": float,
            "yOffset": float,
        }

        Args:
            workflow_dict: worklflow data on the format above

        Returns:
            Tuple of ints workflow_id, workflow_mesh_id, grid_info_id
        """
        raise NotImplementedError()

    def store_data_collection(
        self,
        datacollection_dict: dict,
        beamline_config_dict: dict | None,
    ) -> tuple[int, int]:
        """
        Stores a datacollection, datacollection_dict, and bemline configuration, beamline_config_dict, at the time of collection

        Structure of datacllection_dict:
        {
            "oscillation_sequence":[{}
                "start": float,
                "range": float,
                "overlap": float,
                "number_of_imaages": float,
                "start_image_number": float
                "exposure_time", float,
                "kappaStart": float,
                "phiStart": float,
            }],
            "fileinfo:{
                "direcotry: str,
                "prefix": str
                "suffix": str,
                "template: str,
                "run_number" int
            }
            "status": str,
            "collection_id: int,
            "wavelenght: float,
            "resolution":{
                "lower": float,
                "upper": float
            },
            "resolutionAtCorner": float,
            "detectorDistance": float
            "xBeam": float,
            "yBeam": float,
            "beamSizeAtSampleX": float
            "beamSizeAtSampleY": float,
            "beamShape": str,
            "slitGapHorizontal": float,
            "slitGapVertical": float,
            "synchrotronMode", float,
            "flux": float,
            "flux_end": float,
            "transmission" float,
            "undulatorGap1": float
            "undulatorGap2": float
            "undulatorGap3": float
            "xtalSnapshotFullPath1": str,
            "xtalSnapshotFullPath2": str,
            "xtalSnapshotFullPath3": str,
            "xtalSnapshotFullPath4": str,
            "centeringMethod": str,
            "actualCenteringPosition" str
            "group_id: int,
            "detector_id": int,
            "screening_sub_wedge_id": int,
            "collection_start_time": str #"%Y-%m-%d %H:%M:%S"
        }

        Structure of beamline_config_dict:
        {
            "synchrotron_name":str,
            "directory_prefix":str,
            "default_exposure_time":str,
            "minimum_exposure_time":str,
            "detector_fileext":str,
            "detector_type":str,
            "detector_manufacturer":str,
            "detector_binning_mode":str,
            "detector_model":str,
            "detector_px":int,
            "detector_py":int,
            "undulators":str,
            "focusing_optic":str,
            "monochromator_type":str,
            "beam_divergence_vertical":float,
            "beam_divergence_horizontal":float,
            "polarisation":float,
            "maximum_phi_speed":float,
            "minimum_phi_oscillation":float,
            "input_files_server":str,
        }

        Args:
            datacollection_dict: As defined above
            beamline_config_dict: As defined above

        Returns:
           Tuple data_collection_id, detector_id


        """
        raise NotImplementedError()

    def update_data_collection(
        self,
        datacollection_dict: dict,
    ) -> tuple[int, int]:
        """
        Updates the collection with "collection_id", provided in datacollection_dict.

        Strucure of datacollection_dict as defined in store_data_collection above.

        Args:
            datacollection_dict:

        """
        raise NotImplementedError()

    def finalize_data_collection(
        self,
        datacollection_dict: dict,
    ) -> tuple[int, int]:
        """
        Finalizes the collection with "collection_id", provided in datacollection_dict.

        Strucure of datacollection_dict as defined in store_data_collection above.

        Args:
            datacollection_dict:
        """
        raise NotImplementedError()

    def set_active_session_by_id(self, session_id: str) -> Session:
        """
        Sets session with session_id to active session

        Args:
            session_id: session id
        """
        if self.is_session_already_active(self.session_manager.active_session):
            return self.session_manager.active_session

        if len(self.session_manager.sessions) == 0:
            raise Exception("No sessions available")

        if len(self.session_manager.sessions) == 1:
            self.session_manager.active_session = self.session_manager.sessions[0]
            return self.session_manager.active_session

        session_list = [
            obj
            for obj in self.session_manager.sessions
            if (
                obj.proposal_name.upper() == session_id.upper()
                and obj.is_scheduled_beamline
                and obj.is_scheduled_time
            )
        ]
        self.session_manager.active_session = session_list[0]
        return self.session_manager.active_session
