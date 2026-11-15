from .scenario import Scenario


class SimMotionInput:
    def __init__(self, scenario: Scenario) -> None:
        self._s = scenario

    def motion(self) -> bool:
        return bool(self._s["motion"])

    def close(self) -> None:
        pass
