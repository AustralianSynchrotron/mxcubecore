from gevent import sleep
from mx_robot_library.schemas.common.position import RobotPositions
from mx_robot_library.schemas.common.sample import (
    Pin,
    Plate,
    Puck,
)


class MockPlateTrajectory:
    def mount(self, plate, wait=True):
        print(f"Mock mount called with plate: {plate}, wait: {wait}")
        sleep(2)


class MockTrajectory:
    def __init__(self):
        self.plate = MockPlateTrajectory()


class SimState:
    def __init__(self):
        self.goni_plate = None
        self.goni_pin = None
        self.path = RobotPositions.SOAK


class SimStatus:
    def __init__(self):
        self.state = SimState()
        self.state.goni_plate = Plate(id=1)
        self.state.goni_pin = Pin(id=1, puck=1)

    def get_loaded_trays(self):
        return [
            (1, "ABC-0001"),  # This works with the sim trays of the bluesky worker
            (2, "ABC-0002"),
        ]

    def get_loaded_pucks(self):
        return (
            Puck(
                id=1, name="ABC-0001"
            ),  # This works with the sim pucks of the bluesky worker
            Puck(id=2, name="ABC-0002"),
        )


class MockCommon:
    def abort(self):
        print("Mock abort called")
        return True


class SimRobot:
    def __init__(self):
        self.status = SimStatus()
        self.trajectory = MockTrajectory()
        self.common = MockCommon()


if __name__ == "__main__":

    robot = SimRobot()
    print(robot.status.get_loaded_trays())
    print(robot.status.state.goni_plate)
    print(robot.status.get_loaded_pucks())
    print(robot.status.state.goni_pin)
    print(robot.trajectory.plate.mount(Plate(id=1)))
    print(robot.status.state.path)
    robot.common.abort()
