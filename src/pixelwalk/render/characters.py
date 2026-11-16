"""Characters: a character is a set of sprites named <name>_<pose>, found by naming convention.

Drop a file such as assets/src/char_fox.txt that defines fox_walk, fox_idle, fox_jump, fox_sit and
fox_wake with the sizes and frame counts below, and "fox" becomes selectable (config `hero.character`
or the control page). No code changes. Accessories (umbrella, scarf, sweat) are shared by all
characters and drawn at fixed offsets, so keep the head near where the robot's is.
"""

from __future__ import annotations

from dataclasses import dataclass

from .assets import Assets


@dataclass(frozen=True)
class PoseSpec:
    frames: int  # exact number of frames the code plays
    ground: bool  # feet on the last row of every frame
    size: tuple[int, int] = (16, 16)


POSES: dict[str, PoseSpec] = {
    "walk": PoseSpec(4, True),  # contact and passing poses, 6 fps
    "idle": PoseSpec(2, True),  # 1.5 fps
    "jump": PoseSpec(2, False),  # 0 up, 1 down (the minute bump and the pipe hops)
    "sit": PoseSpec(2, True),  # 0 awake by the fire, 1 asleep
    "wake": PoseSpec(2, True),  # the stretch when motion returns
}
DEFAULT_CHARACTER = "robot"


def sprite_name(character: str, pose: str) -> str:
    return f"{character}_{pose}"


def discover(assets: Assets) -> list[str]:
    """Every name that has a sprite for at least one pose, sorted. Use problems() to check them."""
    names = {
        n[: -len(pose) - 1] for n in assets.sprites for pose in POSES if n.endswith("_" + pose)
    }
    return sorted(names)


def problems(assets: Assets, character: str) -> list[str]:
    """Why `character` cannot be used (empty when it is complete)."""
    out: list[str] = []
    for pose, spec in POSES.items():
        name = sprite_name(character, pose)
        s = assets.sprites.get(name)
        if s is None:
            out.append(f"{name}: missing")
            continue
        if (s.width, s.height) != spec.size:
            out.append(f"{name}: is {s.width}x{s.height}, must be {spec.size[0]}x{spec.size[1]}")
        if len(s.frames) != spec.frames:
            out.append(f"{name}: has {len(s.frames)} frames, must have exactly {spec.frames}")
        if spec.ground and "ground" not in s.flags:
            out.append(f"{name}: needs the 'ground' flag (feet on the last row)")
    return out


def available(assets: Assets) -> list[str]:
    """Complete characters only, the default first."""
    ok = [c for c in discover(assets) if not problems(assets, c)]
    return sorted(ok, key=lambda c: (c != DEFAULT_CHARACTER, c))
