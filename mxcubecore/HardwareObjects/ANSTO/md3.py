import logging
from typing import Annotated, TYPE_CHECKING, Optional
from typing_extensions import Self, overload, Union, Literal, TypeAlias
from pydantic import validate_call, Field, ConfigDict
from gevent import sleep
from mx3_beamline_library.devices.classes.md3.ExportClient import ExporterClient
from mx_robot_library.types import HostAddress

logger = logging.getLogger("HWR")
MD3Phases: TypeAlias = Literal[
    "Centring",
    "DataCollection",
    "BeamLocation",
    "Transfer",
]


class MD3Phase:
    """MD3 Phase Client"""

    if TYPE_CHECKING:
        @overload
        def __init__(self: Self, host: HostAddress, port: Union[int, str]) -> None: ...

        @overload
        def __init__(
            self: Self,
            address: Optional[HostAddress] = None,
            port: Optional[Union[int, str]] = None,
        ) -> None: ...

    @validate_call(
        config=ConfigDict(populate_by_name=True, validate_default=True),
    )
    def __init__(
        self,
        host: Annotated[
            HostAddress,
            Field(
                alias="address",
                default="10.244.101.30",
            ),
        ],
        port: Annotated[
            int,
            Field(default=9001),
        ],
    ) -> None:
        self._client = ExporterClient(address=host, port=port)

    def get(self: Self) -> Union[MD3Phases, Literal["Unknown"]]:
        """Get current MD3 phase.

        Returns:
            MD3Phases | Literal["Unknown"]: Current phase the MD3 is in.
        """
        return self._client.getCurrentPhase()

    if TYPE_CHECKING:
        @overload
        def set(self: Self, value: MD3Phases, wait: bool = True) -> None: ...

    @validate_call
    def set(self, value: MD3Phases, wait: bool = True) -> None:
        """Set MD3 to phase.

        Args:
            value (MD3Phases): Phase to ensure MD3 is changed into.
            wait (bool): Whether to wait for MD3 to finish changing phases,
            before returning or return imediately.
        """
        try:
            if wait:
                # Logic grabbed from: https://github.com/AustralianSynchrotron/mx3-beamline-library/blob/121850d32065fc6bd453630cac232dbbe601483e/mx3_beamline_library/devices/classes/motors.py#L721C77-L742  # noqa
                logger.info(f"Changing MD3 phase from {self.get()} to: {value}")
                # Check if there is an activity still running and wait
                # until this activity has finished before executing another command
                current_phase = self.get()
                while current_phase == "Unknown":
                    sleep(0.2)
                    current_phase = self.get()

                self._client.startSetPhase(value)

                # There is not a wait function on the MD3 phase setter, so the
                # following block a waits for the MD3 to change phase
                current_phase = self.get()
                while current_phase == "Unknown":
                    sleep(0.2)
                    current_phase = self.get()

                status = "Running"
                while status == "Running":
                    status = self._client.getState()
                    sleep(0.1)
                logger.info(f"Phase changed successfully to {self.get()}")
            else:
                # YOLO - Set phase ignoring possibility of errors.
                self._client.startSetPhase(value)
        except Exception as ex:
            # Catch error, logging it, before silently moving on.
            # AKA - Allow the robot to try mounting/unmounting anyway,
            # it might just work 🤷‍♂️.
            logger.error(f"MD3: Failed to set phase to {value} - {str(ex)}")
