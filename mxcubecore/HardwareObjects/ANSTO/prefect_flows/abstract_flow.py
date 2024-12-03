from abc import (
    ABC,
    abstractmethod,
)


class AbstractPrefectWorkflow(ABC):
    """Abstract class to run Bluesky plans as part of
    an mxcubecore workflow. Classes created using this abstract class are meant
    to be used by the BlueskyWorkflow class.

    Attributes
    ----------
    prefect_flow_aborted : bool
        True if a bluesky plan is aborted, False otherwise. False, by default.
    mxcubecore_workflow_aborted : bool
        True if a mxcubecore workflow is aborted, False otherwise. False, by default.
    """

    def __init__(self, state) -> None:
        """
        Parameters
        ----------
        state : State
            The state of the PrefectWorkflow class. See the State class in
            BlueskyWorkflow for details

        Returns
        -------
        None
        """

        super().__init__()
        self._state = state

        self.prefect_flow_aborted = False
        self.mxcubecore_workflow_aborted = False

    @abstractmethod
    def run(self) -> None:
        """
        Runs a prefect flow. Here the flow should be executed with asyncio.run()
        """

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

    @property
    def prefect_flow_aborted(self) -> bool:
        """
        Gets the state of the bluesky plan

        Returns
        -------
        self._value : bool
            The state of the bluesky plan
        """
        return self._prefect_flow_aborted

    @prefect_flow_aborted.setter
    def prefect_flow_aborted(self, value: bool) -> None:
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
        self._prefect_flow_aborted = value

    @property
    def mxcubecore_workflow_aborted(self) -> bool:
        """
        Gets the state of the mxcubecore workflow

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
