from datetime import datetime, time

from ..ports import Clock, Condition, Weather
from .scenario import Scenario


class SimWeather:
    def __init__(self, scenario: Scenario, clock: Clock) -> None:
        self._s = scenario
        self._clock = clock

    def get(self) -> Weather | None:
        s = self._s
        now = self._clock.now()
        try:
            cond = Condition[str(s["weather"]).upper()]
        except KeyError:
            return None
        day = now.date()
        sunrise = datetime.combine(day, time(7, 30), tzinfo=now.tzinfo)
        sunset = datetime.combine(day, time(18, 30), tzinfo=now.tzinfo)
        return Weather(
            condition=cond,
            temperature_c=float(s["outdoor_c"]),
            is_day=sunrise <= now < sunset,
            wind_kmh=float(s["wind_kmh"]),
            gust_kmh=float(s["gust_kmh"]),
            cloud_cover_pct={Condition.CLEAR: 0.0, Condition.PARTLY_CLOUDY: 40.0}.get(cond, 90.0),
            sunrise=sunrise,
            sunset=sunset,
            fetched_at=now,
        )
