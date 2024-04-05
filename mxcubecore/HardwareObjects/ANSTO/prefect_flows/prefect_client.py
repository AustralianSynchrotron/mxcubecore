import asyncio
import logging
from os import environ, path
from uuid import UUID

try:
    from prefect import PrefectClient
    from prefect.server.schemas.filters import FlowRunFilter
    from prefect.server.schemas.responses import FlowRunResponse
    from prefect.server.schemas.states import State, StateType
except ImportError:
    logging.getLogger("HWR").info(
        "Prefect is not installed, prefect flows will not be available"
    )
    FlowRunResponse = None
    State = None

PREFECT_URI = environ.get("PREFECT_URI", "http://localhost:4200")


class MX3PrefectClient:
    """
    Class used to launch prefect flows
    """

    def __init__(self, name: str, parameters: dict) -> None:
        """
        Parameters
        ----------
        name : str
            A deployed flow's name: <FLOW_NAME>/<DEPLOYMENT_NAME>
        parameters : dict
            The flow parameters
        """
        self.parameters = parameters
        self.name = name
        self.flow_run_id = None
        self.deployment_id = None
        self.prefect_client = PrefectClient(api=path.join(PREFECT_URI, "api"))

    async def trigger_flow(self, wait=False) -> FlowRunResponse:
        """
        Triggers a prefect flow

        Parameters
        ----------
        wait : bool, optional
            If wait=True, we wait until the flow has finished, by default False

        Returns
        -------
        FlowRunResponse
            The flow response

        Raises
        ------
        ValueError
            If the flow has not finished successfully
        Exception
            If there has been any other issue during the run
        """
        self.deployment_id = await self.get_deployment_id_from_name(self.name)

        response: FlowRunResponse = (
            await self.prefect_client.create_flow_run_from_deployment(
                self.deployment_id, parameters=self.parameters
            )
        )
        self.flow_run_id = response.id

        if wait:
            await self.wait()

    async def trigger_data_collection(self, poll_interval:float =3.0) -> None:
        """
        Triggers a prefect flow but only waits until data collection is finished
        so that data processing happens in the background

        Parameters
        ----------
        poll_interval : float, optional
            The poll interval in seconds, by default 3.0 seconds

        Returns
        -------
        None
        """
        self.deployment_id = await self.get_deployment_id_from_name(self.name)


        response: FlowRunResponse = (
            await self.prefect_client.create_flow_run_from_deployment(
                self.deployment_id, parameters=self.parameters
            )
        )
        self.flow_run_id = response.id

        task_len = 0
        while task_len == 0:
            await asyncio.sleep(poll_interval)
            tasks = await self.get_tasks()
            task_len = len(tasks)

        state = "RUNNING"
        while state == "RUNNING":
            await asyncio.sleep(poll_interval)
            tasks = await self.get_tasks()
            data_collection_task = tasks[0]
            state = data_collection_task.state.type


    async def get_tasks(self, flow_run_id: UUID = None) -> None:
        """
        Gets prefect tasks

        Parameters
        ----------
        flow_run_id : UUID, optional
            The flow id, by default None

        Returns
        -------
        tasks
            The tasks
        """
        if flow_run_id is None:
            flow_run_id = self.flow_run_id

        q = FlowRunFilter(id={"any_": [flow_run_id]})
        tasks = await self.prefect_client.read_task_runs(flow_run_filter=q)
        return tasks



    async def wait(self) -> None:
        """
        Wait until a flow is completed.

        Raises
        ------
        ValueError
            Raises an error if the final state of the flow is not
            COMPLETED
        """
        state = await self.get_flow_run_state()
        while (
            state.type == StateType.SCHEDULED  # noqa
            or state.type == StateType.PENDING  # noqa
            or state.type == StateType.RUNNING  # noqa
        ):
            state = await self.get_flow_run_state()
            await asyncio.sleep(3)

        if state.type == StateType.COMPLETED:
            print("FLow completed successfully!")
        else:
            raise ValueError(
                "Something has gone wrong. The current "
                f"state of the flow is {state.type}"
            )

    async def get_deployment_id_from_name(self, name: str) -> UUID:
        """
        Gets the deployment id from the name of the flow

        Parameters
        ----------
        name : str
            A deployed flow's name: <FLOW_NAME>/<DEPLOYMENT_NAME>

        Returns
        -------
        UUID
            The deployment ID
        """
        result = await self.prefect_client.read_deployment_by_name(name)
        return result.id

    async def get_flow_run_state(self, flow_run_id: UUID = None) -> State:
        """
        Gets the state of a run

        Parameters
        ----------
        flow_run_id : UUID, optional
            The id of the run, by default None

        Returns
        -------
        State
            the state of the run

        Raises
        ------
        RuntimeError
            An error if the state could not be obtained
        """
        if flow_run_id is None:
            flow_run_id = self.flow_run_id
        try:
            flow_run = await self.get_flow_runs(flow_run_id)
            return flow_run[0].state
        except Exception as e:
            raise RuntimeError(
                f"Failed to get flow run state for {flow_run_id}: {str(e)}"
            )

    async def get_flow_runs(self, flow_run_id: UUID = None) -> list[FlowRunResponse]:
        """Gets prefect flow runs

        Parameters
        ----------
        flow_run_id : UUID, optional
            The flow run ID, by default None

        Returns
        -------
        list[FlowRunResponse]
            A list of flow response
        """
        if flow_run_id is None:
            flow_run_id = self.flow_run_id
        q = FlowRunFilter(id={"any_": [flow_run_id]})
        try:
            return await self.prefect_client.read_flow_runs(flow_run_filter=q)
        except Exception as e:
            raise RuntimeError(f"Cannot get flow runs for {flow_run_id}: {str(e)}")
