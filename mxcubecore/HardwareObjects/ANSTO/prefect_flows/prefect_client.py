import asyncio
import logging
from enum import StrEnum
from os import (
    environ,
    path,
)
from uuid import UUID

import redis

from mxcubecore.configuration.ansto.config import settings

try:
    # NOTE: State must be imported first,
    # otherwise the prefect client does not work properly
    from prefect import State  # noqa
    from prefect.client.orchestration import PrefectClient
    from prefect.server.schemas.filters import FlowRunFilter
    from prefect.server.schemas.responses import FlowRunResponse
    from prefect.server.schemas.states import StateType  # noqa

except ImportError:
    logging.getLogger("HWR").info(
        "Prefect is not installed, prefect flows will not be available"
    )
    FlowRunResponse = None
    State = None

PREFECT_URI = environ.get("PREFECT_URI", "http://localhost:4200")


class FlowState(StrEnum):
    RUNNING = "running"
    FAILED = "failed"
    READY_TO_UNMOUNT = "ready_to_unmount"  # This does not mean the flow is completed
    COMPLETED = "completed"


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

        self.async_redis_connection = redis.asyncio.StrictRedis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            username=settings.REDIS_USERNAME,
            password=settings.REDIS_PASSWORD,
            db=settings.REDIS_DB,
            decode_responses=True,
        )

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

    async def trigger_grid_scan(self) -> FlowRunResponse:
        """
        Triggers a grid scans and waits until the flow state has
        changed from scheduled or pending to running

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

        state = await self.get_flow_run_state()
        while (
            state.type == StateType.SCHEDULED  # noqa
            or state.type == StateType.PENDING  # noqa
        ):
            state = await self.get_flow_run_state()
            await asyncio.sleep(1)

    async def trigger_data_collection(
        self, sample_id: str, poll_interval: float = 3.0
    ) -> None:
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
        await self.async_redis_connection.set(
            f"mxcube_scan_state:{sample_id}", FlowState.RUNNING, ex=3600
        )

        response: FlowRunResponse = (
            await self.prefect_client.create_flow_run_from_deployment(
                self.deployment_id, parameters=self.parameters
            )
        )
        self.flow_run_id = response.id

        flow_status = await self.async_redis_connection.get(
            f"mxcube_scan_state:{sample_id}"
        )
        while flow_status not in [FlowState.FAILED, FlowState.READY_TO_UNMOUNT]:
            await asyncio.sleep(poll_interval)
            flow_status = await self.async_redis_connection.get(
                f"mxcube_scan_state:{sample_id}"
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
        flow_run = await self.get_flow_runs(flow_run_id)
        return flow_run[0].state

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
        return await self.prefect_client.read_flow_runs(flow_run_filter=q)
