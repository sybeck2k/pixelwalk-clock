"""WMO weather code -> Condition (spec 5.5). Open-Meteo reports WMO codes."""

from __future__ import annotations

from ..ports import Condition

_TABLE: dict[int, Condition] = {}
for _codes, _cond in (
    ((0, 1), Condition.CLEAR),
    ((2,), Condition.PARTLY_CLOUDY),
    ((3,), Condition.OVERCAST),
    ((45, 48), Condition.FOG),
    ((51, 53, 55, 56, 57), Condition.DRIZZLE),
    ((61, 63, 66, 80, 81), Condition.RAIN),
    ((65, 67, 82), Condition.HEAVY_RAIN),
    ((71, 73, 75, 77, 85, 86), Condition.SNOW),
    ((95, 96, 97, 99), Condition.THUNDER),
):
    for _c in _codes:
        _TABLE[_c] = _cond


def condition_from_wmo(code: float | None) -> Condition:
    """Unknown or missing codes map to OVERCAST, as the spec says."""
    try:
        return _TABLE.get(int(code), Condition.OVERCAST)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return Condition.OVERCAST
