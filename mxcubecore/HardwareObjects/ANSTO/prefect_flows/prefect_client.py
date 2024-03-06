import asyncio
from os import environ, path
from uuid import UUID

from pendulum import now
from pendulum.datetime import DateTime
from prefect import PrefectClient
from prefect.client.schemas import OrchestrationResult
from prefect.client.schemas.responses import DeploymentResponse
from prefect.server.schemas.filters import FlowRunFilter
from prefect.server.schemas.responses import FlowRunResponse
from prefect.server.schemas.states import State, StateDetails, StateType
from prefect.server.utilities.schemas.fields import DateTimeTZ
import logging

PREFECT_URI = environ.get("PREFECT_URI", "http://localhost:4200")


class MX3PrefectClient:
    """
    Code taken from the mx-prefect-bluesky-work-pool
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

        try:
            response: FlowRunResponse = (
                await self.prefect_client.create_flow_run_from_deployment(
                    self.deployment_id, parameters=self.parameters
                )
            )
            self.flow_run_id = response.id

            if wait:
                await self.wait()
        except Exception as e:
            logging.getLogger("HWR").info(f"Flow execution failed {e}")
            

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

    async def get_flow_runs(self, flow_run_id: UUID = None) -> list[FlowRunResponse]:
        """
        Get flow run details.

        :param flow_run_id:
        :return: list[FlowRunResponse]
        """
        if flow_run_id is None:
            flow_run_id = self.flow_run_id
        q = FlowRunFilter(id={"any_": [flow_run_id]})
        try:
            return await self.prefect_client.read_flow_runs(flow_run_filter=q)
        except Exception as e:
            raise RuntimeError(f"Cannot get flow runs for {flow_run_id}: {str(e)}")

    async def get_flow_runs_from_parent_flow(
        self, flow_run_id: UUID = None
    ) -> list[FlowRunResponse]:
        if flow_run_id is None:
            flow_run_id = self.flow_run_id
        q = FlowRunFilter(parent_flow_run_id={"any_": [flow_run_id]})
        try:
            return await self.prefect_client.read_flow_runs(flow_run_filter=q)
        except Exception as e:
            raise RuntimeError(f"Cannot get flow runs for {flow_run_id}: {str(e)}")

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

        Raises
        ------
        RuntimeError
            An error if something has gone wrong
        """
        if flow_run_id is None:
            flow_run_id = self.flow_run_id
        try:
            q = FlowRunFilter(id={"any_": [flow_run_id]})
            tasks = await self.prefect_client.read_task_runs(flow_run_filter=q)
            return tasks
        except Exception as e:
            raise RuntimeError(f"failed to get tasks for {flow_run_id}: {str(e)}")

    async def get_flow_status(self, flow_run_id: UUID = None) -> None:
        """
        Gets the status of the flow

        Parameters
        ----------
        flow_run_id : UUID, optional
            The flow id, by default None

        Returns
        -------
        tasks_obj
            The task object

        Raises
        ------
        RuntimeError
             An error if something has gone wrong
        """
        if flow_run_id is None:
            flow_run_id = self.flow_run_id
        try:
            flow = await self.get_flow_runs(flow_run_id)
            tasks = await self.get_tasks(flow_run_id)
            # Lets get each task's id, name and status
            tasks_obj = [
                {"id": task.id, "name": task.name, "status": task.state_type}
                for task in tasks
            ]
            # Let's get the flow's id, name and status
            flow_obj = {
                "flow": {
                    "id": flow[0].id,
                    "name": flow[0].name,
                    "status": flow[0].state_type,
                },
                "tasks": tasks_obj,
            }
            return flow_obj
        except Exception as e:
            raise RuntimeError(
                f"Failed to fetch flow status for flow run ID {flow_run_id}: {str(e)}"
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

    async def get_deployment_from_name(self, name: str) -> DeploymentResponse:
        """
        Gets the deployment from the name of the flow

        Parameters
        ----------
        name : str
            A deployed flow's name: <FLOW_NAME>/<DEPLOYMENT_NAME>

        Returns
        -------
        UUID
            The deployment ID
        """
        return await self.prefect_client.read_deployment_by_name(name)

    async def _pause_flow(
        self, flow_run_id: UUID, timeout: float
    ) -> OrchestrationResult:
        # Pause the parent flow
        timeout: DateTime = now().add(seconds=timeout)
        response = await self.prefect_client.set_flow_run_state(
            flow_run_id,
            state=State(
                name="Paused",
                type=StateType.PAUSED,
                state_details=StateDetails(
                    pause_reschedule=True,
                    pause_timeout=DateTimeTZ(
                        year=timeout.year,
                        month=timeout.month,
                        day=timeout.month,
                        hour=timeout.hour,
                        minute=timeout.minute,
                        second=timeout.second,
                        microsecond=timeout.microsecond,
                        tzinfo=timeout.tzinfo,
                        fold=timeout.fold,
                    ),
                ),
            ),
            force=True,
        )
        return response

    async def _resume_flow(
        self, flow_run_id: UUID, timeout: float = 300
    ) -> OrchestrationResult:
        # Pause the parent flow
        timeout: DateTime = now().add(seconds=timeout)
        response = await self.prefect_client.set_flow_run_state(
            flow_run_id,
            state=State(
                name="Running",
                type=StateType.RUNNING,
                state_details=StateDetails(
                    pause_reschedule=True,
                    pause_timeout=DateTimeTZ(
                        year=timeout.year,
                        month=timeout.month,
                        day=timeout.month,
                        hour=timeout.hour,
                        minute=timeout.minute,
                        second=timeout.second,
                        microsecond=timeout.microsecond,
                        tzinfo=timeout.tzinfo,
                        fold=timeout.fold,
                    ),
                ),
            ),
            force=True,
        )
        return response

    async def pause_flow(self, timeout: float = 300) -> list[OrchestrationResult]:
        # Pause Parent flow
        result = []
        # res = await self._pause_flow(self.flow_run_id,timeout=timeout)
        # result.append(res)
        await asyncio.sleep(0.3)
        # Pause all child flows that containing a flow run id
        flow_runs = await self.get_flow_runs_from_parent_flow()
        for flow in flow_runs:
            if flow.state.type == StateType.RUNNING:
                res = await self._pause_flow(flow.id, timeout=timeout)
                result.append(res)
                await asyncio.sleep(0.3)

        return result

    async def resume_flow(self):
        flow_runs = await self.get_flow_runs_from_parent_flow()
        result = []
        for flow in flow_runs:
            if flow.state.type == StateType.PAUSED:
                res = await self._resume_flow(flow.id)
                result.append(res)
                await asyncio.sleep(0.3)

        # res = await prefect_client.resume_flow_run(self.flow_run_id)
        # result.append(res)
        return result