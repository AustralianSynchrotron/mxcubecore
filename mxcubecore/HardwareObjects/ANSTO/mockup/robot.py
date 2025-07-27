from mx_robot_library.schemas.common.sample import (
    Pin,
    Plate,
    Puck,
)


class SimState:
    def __init__(self):
        self.goni_plate = None
        self.goni_pin = None


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


class SimRobot:
    def __init__(self):
        self.status = SimStatus()


if __name__ == "__main__":

    robot = SimRobot()
    print(robot.status.get_loaded_trays())
    print(robot.status.state.goni_plate)
    print(robot.status.get_loaded_pucks())
    print(robot.status.state.goni_pin)
