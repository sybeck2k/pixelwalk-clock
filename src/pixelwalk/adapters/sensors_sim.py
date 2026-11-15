from ..ports import Clock, SensorReading
from .scenario import Scenario


class SimSensors:
    def __init__(self, scenario: Scenario, clock: Clock) -> None:
        self._s = scenario
        self._clock = clock

    def read(self) -> SensorReading:
        s = self._s
        return SensorReading(
            lux=float(s["lux"]),
            temperature_c=float(s["indoor_c"]),
            humidity_pct=float(s["humidity"]),
            pressure_hpa=float(s["pressure_hpa"]),
            at=self._clock.now(),
        )
