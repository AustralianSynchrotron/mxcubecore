import logging
from enum import StrEnum
from uuid import UUID

import redis
from gevent import sleep

from mxcubecore.configuration.ansto.config import settings

try:
    # NOTE: State must be imported first,
    # otherwise the prefect client does not work properly
    from prefect import State  # noqa
    from prefect.client.orchestration import get_client
    from prefect.server.schemas.responses import FlowRunResponse


except ImportError:
    logging.getLogger("HWR").info(
        "Prefect is not installed, prefect flows will not be available"
    )
    FlowRunResponse = None
    State = None


class FlowState(StrEnum):
    RUNNING = "running"
    FAILED = "failed"
    READY_TO_UNMOUNT = "ready_to_unmount"
    COMPLETED = "completed"


class MX3SyncPrefectClient:
    """Synchronous implementation of the prefect client.
    The prefect URL has to be set via the command line by
    running:

    prefect config set PREFECT_API_URL=${PREFECT_API_URL}

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
        self.redis_connection = redis.StrictRedis(
            host=settings.MXCUBE_REDIS_HOST,
            port=settings.MXCUBE_REDIS_PORT,
            username=settings.MXCUBE_REDIS_USERNAME,
            password=settings.MXCUBE_REDIS_PASSWORD,
            db=settings.MXCUBE_REDIS_DB,
            decode_responses=True,
        )

    def get_deployment_id_from_name(self, name: str) -> UUID:
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

        with get_client(sync_client=True) as client:
            result = client.read_deployment_by_name(name)
        return result.id

    def trigger_flow(self, wait=False, poll_interval=3) -> FlowRunResponse:
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
        self.deployment_id = self.get_deployment_id_from_name(self.name)

        with get_client(sync_client=True) as client:

            response = client.create_flow_run_from_deployment(
                self.deployment_id, parameters=self.parameters
            )
            self.flow_run_id = response.id

            if wait:
                while True:
                    flow_run = client.read_flow_run(self.flow_run_id)
                    flow_state = flow_run.state
                    if flow_state and flow_state.is_final():
                        return flow_run
                    sleep(poll_interval)

    def trigger_data_collection(
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
        self.deployment_id = self.get_deployment_id_from_name(self.name)
        self.redis_connection.set(
            f"mxcube_scan_state:{sample_id}", FlowState.RUNNING, ex=3600
        )

        with get_client(sync_client=True) as client:

            response: FlowRunResponse = client.create_flow_run_from_deployment(
                self.deployment_id, parameters=self.parameters
            )
            self.flow_run_id = response.id

            flow_status = self.redis_connection.get(f"mxcube_scan_state:{sample_id}")
            while flow_status not in [
                FlowState.FAILED,
                FlowState.READY_TO_UNMOUNT,
                FlowState.COMPLETED,
            ]:
                sleep(poll_interval)
                flow_status = self.redis_connection.get(
                    f"mxcube_scan_state:{sample_id}"
                )
