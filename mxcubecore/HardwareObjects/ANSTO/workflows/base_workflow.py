from abc import ABC, abstractmethod
from mxcubecore.HardwareObjects.ANSTO.OphydEpicsMotor import OphydEpicsMotor
import asyncio


class AbstractBlueskyWorflow(ABC):
    def __init__(self, state, REST: str) -> None:
        super().__init__()

        self._state = state
        self.REST = REST

        self.dialog_box_parameters = None
        self.bluesky_plan_aborted = False
        self.mxcubecore_workflow_aborted = False

    @abstractmethod
    def run(self) -> None:
        """
        Runs a bluesky plan
        """
        pass

    @abstractmethod
    def dialog_box(self) -> dict:
        """
        Workflow dialog box. Returns a dictionary that follows a JSON schema

        Returns
        -------
        dialog : dict
            A dictionary that follows a JSON schema.
        """
        dialog = {
            "properties": {
                "name": {
                    "title": "Task name",
                    "type": "string",
                    "minLength": 2,
                    "default": "Test",
                },
            },
            "required": ["name"],
            "dialogName": "My Workflow parameters",
        }
        return dialog

    async def update_frontend_values(self, motor: OphydEpicsMotor) -> None:
        """
        Update the motor values in the Web UI

        Parameters
        ----------
        motor : OphydEpicsMotor
            An OphydEpicsMotor object

        Returns
        -------
        None
        """
        motor.update_specific_state(motor.SPECIFIC_STATES.MOVING)

        motor.update_state(motor.STATES.BUSY)
        current_value = motor.get_value()
        motor.update_value(current_value)
        await asyncio.sleep(0.01)

    @property
    def bluesky_plan_aborted(self) -> bool:
        """
        Gets the state of the bluesky plan

        Returns
        -------
        self._value : bool
            The state of the bluesky plan
        """
        return self._bluesky_plan_aborted

    @bluesky_plan_aborted.setter
    def bluesky_plan_aborted(self, value: bool) -> None:
        """
        Sets the state of the bluesky plan

        Parameters
        ----------
        value : bool
            The state of the bluesky plan

        Returns
        -------
        None
        """
        self._bluesky_plan_aborted = value

    @property
    def mxcubecore_workflow_aborted(self) -> bool:
        """
        Gets the state of the mxcubecore worflow

        Returns
        -------
        self._value: bool
            The state of the mxcubecore workflow
        """
        return self._mxcubecore_workflow_aborted

    @mxcubecore_workflow_aborted.setter
    def mxcubecore_workflow_aborted(self, value: bool) -> None:
        """
        Sets the state of the mxcubecore workflow

        Returns
        -------
        None
        """
        self._mxcubecore_workflow_aborted = value

    @property
    def dialog_box_parameters(self) -> dict:
        """
        Gets the dialog box parameters

        Returns
        -------
        self._value : dict
            The dialog box parameters
        """
        return self._dialog_box_parameters

    @dialog_box_parameters.setter
    def dialog_box_parameters(self, value: dict) -> None:
        """
        Sets the updated dialog box parameters

        Parameters
        ----------
        value : dict
            The updated dialog box parameters

        Returns
        -------
        None
        """
        self._dialog_box_parameters = value

    @property
    def state(self):
        """
        Gets the state of the workflow

        Returns
        -------
        _state : State
            The state of the workflow
        """
        return self._state

    @state.setter
    def state(self, new_state) -> None:
        """
        Sets the state of the workflow

        Parameters
        ----------
        new_state : State
            The state of the workflow

        Returns
        -------
        None
        """
        self._state = new_state
