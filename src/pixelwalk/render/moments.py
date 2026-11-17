"""Drawing and choreography for moments (see logic/moments.py): cameos, sky visitors, stories and
scenery changes. Pillow calls only; every sprite is tinted and mirrored once, at start-up.

A moment draws in up to three places in the frame, back to front:
  sky     after the sky and clouds, before the scenery strips (a UFO passes behind the hills)
  world   after the strips, before the hero (a deer on the ground, the chest, a friend)
  front   after the hero (fireworks, a sandstorm, a red-alert wash)
and may take the hero over (a story): `step` returns a HeroOverride, or None to let it walk.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from typing import ClassVar

from PIL import Image, ImageChops, ImageDraw, ImageOps

from ..logic.astro import Phase
from ..logic.clockface import GROUND_Y, HOME_X, HeroOverride
from ..logic.moments import ActiveMoment
from .assets import Assets
from .events import Sparkles
from .phases import remap_image

FEET = GROUND_Y + 18  # one past the last row of things that walk on the ground line (just inside it)
SPRITES = (
    "bus", "deer", "reindeer", "camel", "knight", "bat", "droid", "ghost", "ufo", "balloon", "plane", "chest", "note",
)
HERO_W = 16
FADE_STEPS = 16


def envelope(p: float, edge: float = 0.12) -> float:
    """0 to 1 and back to 0 over progress p: fades a scene in and out."""
    return max(0.0, min(1.0, p / edge, (1.0 - p) / edge))


def hop(since: float, period: float = 0.5, height: int = 5) -> HeroOverride:
    """The hero's hop: up on the first half of each period, down on the second."""
    phase = (since / period) % 1.0
    return HeroOverride(HOME_X, GROUND_Y - round(height * math.sin(math.pi * phase)), "jump_up" if phase < 0.5 else "jump_down")


class Sprites:
    """Tinted (per time of day) and mirrored frames of the moment sprites."""

    def __init__(self, assets: Assets, actor: dict[Phase, dict]) -> None:
        master = assets.palette
        self._frames = {
            p: {n: [remap_image(f, master, actor[p]) for f in assets[n].frames] for n in SPRITES} for p in Phase
        }
        self._flipped: dict[tuple, list[Image.Image]] = {}

    def get(self, name: str, phase: Phase, flip: bool = False) -> list[Image.Image]:
        if not flip:
            return self._frames[phase][name]
        key = (phase, name)
        if key not in self._flipped:
            self._flipped[key] = [ImageOps.mirror(f) for f in self._frames[phase][name]]
        return self._flipped[key]


class Context:
    """What a moment can use: sprites, palettes, sparkles, the wash and the friend's frames."""

    def __init__(
        self,
        sprites: Sprites,
        width: int,
        height: int,
        scene_pal: dict[Phase, dict],
        sparkles: Sparkles,
        wash: Callable,
        friend: Callable[[Phase], dict | None],
    ) -> None:
        self.sprites, self.width, self.height, self.scene_pal = sprites, width, height, scene_pal
        self.sparkles, self.wash, self.friend = sparkles, wash, friend


class Moment:
    """One playing moment. Subclasses override what they need."""

    layer: ClassVar[str] = "world"  # where a crossing draws: "sky" or "world"

    def __init__(self, ctx: Context, am: ActiveMoment, world_x: float) -> None:
        self.ctx, self.am = ctx, am
        self.rng = random.Random(am.seed)
        self.done = False
        self.t0 = am.start
        self.start(world_x)

    def start(self, world_x: float) -> None:
        pass

    def step(self, t: float, dt: float, world_x: float) -> HeroOverride | None:
        if t >= self.t0 + self.am.duration_s:
            self.done = True
        return None

    def sky(self, img: Image.Image, t: float, phase: Phase) -> None:
        pass

    def world(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        pass

    def front(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        pass

    def progress(self, t: float) -> float:
        return self.am.progress(t)


# --- cameos and sky visitors: something crosses the screen ---------------------------------

# name -> (sprite, fps, y range or None for "on the ground", wobble in px, layer)
CROSSERS: dict[str, tuple[str, float, tuple[int, int] | None, int, str]] = {
    "bus": ("bus", 6.0, None, 0, "world"),
    "deer": ("deer", 5.0, None, 0, "world"),
    "reindeer": ("reindeer", 5.0, None, 0, "world"),
    "camel": ("camel", 4.0, None, 0, "world"),
    "knight": ("knight", 8.0, None, 0, "world"),
    "droid": ("droid", 4.0, (27, 34), 2, "world"),
    "ghost": ("ghost", 2.0, (27, 34), 2, "world"),
    "ufo": ("ufo", 3.0, (23, 30), 1, "sky"),  # between the clock blocks and the horizon
    "plane": ("plane", 1.0, (23, 29), 0, "sky"),
    "balloon": ("balloon", 1.0, (19, 24), 0, "sky"),
}


class Crosser(Moment):
    def start(self, world_x: float) -> None:
        self.name = self.am.name
        self.sprite, self.fps, self.yr, self.wobble, self.layer = CROSSERS[self.name]
        self.rightward = self.rng.random() < 0.5
        self.y0 = self.rng.randint(*self.yr) if self.yr else 0
        self.bob = self.rng.random() * 6.0

    def _draw(self, img: Image.Image, t: float, phase: Phase) -> None:
        frames = self.ctx.sprites.get(self.sprite, phase, flip=not self.rightward)
        frame = frames[int((t - self.t0) * self.fps) % len(frames)]
        p = self.progress(t)
        span = self.ctx.width + 2 * frame.width
        x = -frame.width + p * span if self.rightward else self.ctx.width + frame.width - p * span - frame.width
        if self.yr is None:
            y = FEET - frame.height
        else:
            y = self.y0 + round(self.wobble * math.sin((t - self.t0) * 2.0 + self.bob))
            if self.name == "balloon":
                y -= round(3 * p)  # it climbs slowly
        if self.name == "plane":  # a contrail behind it, dotted
            d = ImageDraw.Draw(img)
            sign = -1 if self.rightward else 1
            col = self.ctx.scene_pal[phase]["w"]
            for k in range(3, 34):
                cx = round(x) + (frame.width if not self.rightward else 0) + sign * k
                if 0 <= cx < self.ctx.width and k % 4 != 3:
                    d.point((cx, y + 1), fill=col)
        img.paste(frame, (round(x), y), frame)

    def sky(self, img: Image.Image, t: float, phase: Phase) -> None:
        if self.layer == "sky":
            self._draw(img, t, phase)

    def world(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        if self.layer == "world":
            self._draw(img, t, phase)


class Bats(Moment):
    """A few bats flit across the cave."""

    def start(self, world_x: float) -> None:
        self.rightward = self.rng.random() < 0.5
        self.bats = [(self.rng.uniform(-0.12, 0.0) * i, self.rng.randint(26, 38), self.rng.uniform(0, 6)) for i in range(4)]

    def world(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        frames = self.ctx.sprites.get("bat", phase)
        p = self.progress(t)
        for lag, y0, ph in self.bats:
            q = p + lag
            if not 0 <= q <= 1:
                continue
            x = -6 + q * (self.ctx.width + 12)
            x = x if self.rightward else self.ctx.width - 6 - x
            y = y0 + round(4 * math.sin((t - self.t0) * 3 + ph))
            f = frames[int((t - self.t0) * 9 + ph) % 2]
            img.paste(f, (round(x), y), f)

    def step(self, t: float, dt: float, world_x: float) -> HeroOverride | None:
        if t >= self.t0 + self.am.duration_s * 1.15:
            self.done = True
        return None


class Rainbow(Moment):
    layer = "sky"
    BANDS = "rByguv"

    def start(self, world_x: float) -> None:
        self._layers: dict[Phase, Image.Image] = {}
        self._fade: dict[tuple, Image.Image] = {}
        self.cx = self.rng.randint(22, 42)

    def _layer(self, phase: Phase) -> Image.Image:
        if phase not in self._layers:
            pal = self.ctx.scene_pal[phase]
            img = Image.new("RGBA", (self.ctx.width, 40), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            for i, ch in enumerate(self.BANDS):
                r = 38 - 2 * i
                d.arc((self.cx - r, 56 - r, self.cx + r, 56 + r), 180, 360, fill=(*pal[ch], 255), width=2)
            self._layers[phase] = img
        return self._layers[phase]

    def sky(self, img: Image.Image, t: float, phase: Phase) -> None:
        q = round(envelope(self.progress(t), 0.2) * FADE_STEPS)
        if q == 0:
            return
        layer = self._layer(phase)
        key = (phase, q)
        if key not in self._fade:
            self._fade[key] = ImageChops.multiply(layer.getchannel("A"), Image.new("L", layer.size, q * 255 // FADE_STEPS))
        img.paste(layer, (0, 2), self._fade[key])


def _streak(d: ImageDraw.ImageDraw, p: float, seed: int, pal: dict) -> None:
    """A meteor: a bright head and a long fading tail, falling down and to one side."""
    rng = random.Random(seed)
    sign = -1 if rng.random() < 0.5 else 1
    x0, y0 = rng.randint(14, 58), rng.randint(3, 16)
    hx, hy = x0 + sign * 40 * p, y0 + 24 * p
    d.point((round(hx), round(hy)), fill=pal["w"])
    for i, colour in enumerate("wwyyYY", start=1):
        d.point((round(hx - sign * i * 1.7), round(hy - i)), fill=pal[colour])


class Meteors(Moment):
    layer = "sky"

    def start(self, world_x: float) -> None:
        n = 10
        self.stars = [(i * (self.am.duration_s - 1.5) / n + self.rng.uniform(0, 0.6), self.rng.randrange(1 << 30)) for i in range(n)]

    def sky(self, img: Image.Image, t: float, phase: Phase) -> None:
        d = ImageDraw.Draw(img)
        for start, seed in self.stars:
            p = (t - self.t0 - start) / 1.3
            if 0 <= p <= 1:
                _streak(d, p, seed, self.ctx.scene_pal[phase])


# --- scenery moments -----------------------------------------------------------------------


class Aurora(Moment):
    layer = "sky"

    def sky(self, img: Image.Image, t: float, phase: Phase) -> None:
        e = envelope(self.progress(t), 0.15)
        if e <= 0:
            return
        pal = self.ctx.scene_pal[phase]
        d = ImageDraw.Draw(img)
        s = t - self.t0
        for x in range(self.ctx.width):
            if (x * 5 + int(s * 3)) % 4 == 0:  # a shimmer: some columns blink out
                continue
            top = 3 + 3 * math.sin(x * 0.16 + s * 0.5) + 2 * math.sin(x * 0.4 - s * 0.9)
            length = round(e * (9 + 5 * math.sin(x * 0.27 - s * 0.7)))
            if length <= 0:
                continue
            y0 = round(top) + 22 - length // 2 if x % 2 else round(top) + 20 - length // 2
            d.line((x, y0, x, y0 + length // 2), fill=pal["g"])
            d.line((x, y0 + length // 2 + 1, x, y0 + length), fill=pal["t"])
            if length > 6:
                d.point((x, y0 + length + 1), fill=pal["c"])


class Fireworks(Moment):
    def start(self, world_x: float) -> None:
        n = 7
        self.bursts = [
            (
                i * (self.am.duration_s - 3) / n + self.rng.uniform(0, 0.8),
                self.rng.randint(8, 56), self.rng.randint(24, 33),
                self.rng.choice(("rpc", "ywp", "ycw", "pBy", "gcw")),
            )
            for i in range(n)
        ]

    def front(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        d = ImageDraw.Draw(img)
        pal = self.ctx.scene_pal[phase]
        for start, x, y, cols in self.bursts:
            s = t - self.t0 - start
            if s < 0 or s > 2.0:
                continue
            if s < 0.5:  # the rocket climbs
                d.point((x, round(40 - (40 - y) * s / 0.5)), fill=pal["y"])
                continue
            q = (s - 0.5) / 1.5
            grow = 1 - (1 - min(1.0, q * 1.3)) ** 2
            for ring, (n, radius) in enumerate(((20, 11), (10, 6))):  # an outer shell and an inner one
                r = radius * grow
                for k in range(n):
                    a = k * math.tau / n + ring * 0.3
                    px, py = round(x + r * math.cos(a)), round(y + r * math.sin(a) + 5 * q * q)
                    if q > 0.65 and (k + int(s * 12)) % 2:
                        continue  # the sparks die out, blinking
                    if 0 <= px < self.ctx.width and 0 <= py < self.ctx.height:
                        d.point((px, py), fill=pal[cols[(k + ring) % len(cols)]])


class Sandstorm(Moment):
    def start(self, world_x: float) -> None:
        self.streaks = [(self.rng.uniform(0, 72), self.rng.randint(26, 62), self.rng.uniform(40, 80), self.rng.randint(3, 6)) for _ in range(34)]

    def front(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        e = envelope(self.progress(t), 0.18)
        pal = self.ctx.scene_pal[phase]
        self.ctx.wash(img, pal["n"], (0, 22, self.ctx.width, self.ctx.height), 0.42 * e)
        d = ImageDraw.Draw(img)
        s = t - self.t0
        for i, (x0, y, speed, n) in enumerate(self.streaks):
            if i / len(self.streaks) > e:
                continue
            x = round((x0 - speed * s) % (self.ctx.width + 12)) - 6
            d.line((x, y, x + n, y), fill=pal["N" if i % 3 else "Y"])


class HallStorm(Moment):
    FLASHES = ((0.8, 0.18), (1.25, 0.12), (3.6, 0.2), (4.0, 0.1), (6.4, 0.22))

    def front(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        s = t - self.t0
        for at, length in self.FLASHES:
            if at <= s < at + length:
                self.ctx.wash(img, (205, 220, 255), (0, 0, self.ctx.width, self.ctx.height), 0.45 if s < at + length / 2 else 0.22)
                return


class RedAlert(Moment):
    def front(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        s = t - self.t0
        level = 0.34 * (0.5 + 0.5 * math.sin(math.tau * 1.1 * s - math.pi / 2)) * envelope(self.progress(t), 0.1)
        self.ctx.wash(img, (230, 30, 40), (0, 0, self.ctx.width, self.ctx.height), level)


class CaveGlow(Moment):
    def start(self, world_x: float) -> None:
        self.motes = [(self.rng.randint(2, 61), self.rng.uniform(26, 60), self.rng.uniform(1.0, 3.0), self.rng.uniform(0, 6)) for _ in range(18)]

    def front(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        e = envelope(self.progress(t), 0.2)
        pal = self.ctx.scene_pal[phase]
        d = ImageDraw.Draw(img)
        s = t - self.t0
        for i, (x0, y0, speed, ph) in enumerate(self.motes):
            if i / len(self.motes) > e:
                continue
            x = round(x0 + 3 * math.sin(s * 0.8 + ph))
            y = round(26 + (y0 - 26 - speed * s * 2.0) % 34)
            d.point((x, y), fill=pal["w" if int(s * 3 + ph) % 3 == 0 else "c"])


# --- stories: the hero is in it ------------------------------------------------------------


class Chest(Moment):
    """A chest comes up the road; the hero stops, opens it, and cheers."""

    def start(self, world_x: float) -> None:
        self.wx = world_x + self.ctx.width + 4  # fixed in the world, so the ground carries it along
        self.stage, self.ts = "approach", self.t0
        self.burst = False

    def _x(self, world_x: float) -> float:
        return self.wx - world_x

    def step(self, t: float, dt: float, world_x: float) -> HeroOverride | None:
        sx = self._x(world_x)
        if t - self.t0 > 70:
            self.done = True
        if self.stage == "approach":
            if sx <= HOME_X + HERO_W + 1:
                self.stage, self.ts = "open", t
            return None
        s = t - self.ts
        if self.stage == "open":
            if s >= 1.8 and not self.burst:
                self.burst = True
                self.ctx.sparkles.burst(sx + 6, FEET - 12, 18)
            if s >= 2.8:
                self.stage, self.ts = "cheer", t
            return HeroOverride(HOME_X, GROUND_Y, "stand")
        if self.stage == "cheer":
            if s >= 1.5:
                self.stage = "leave"
                return None
            return hop(s, 0.5, 5)
        if sx < -14:
            self.done = True
        return None

    def world(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        frames = self.ctx.sprites.get("chest", phase)
        s = t - self.ts
        frame = frames[0]
        if self.stage == "open":
            frame = frames[0] if s < 1.0 else frames[1] if s < 1.8 else frames[2]
        elif self.stage in ("cheer", "leave"):
            frame = frames[2]
        img.paste(frame, (round(self._x(world_x)), FEET - 1 - frame.height + 1), frame)


class Friend(Moment):
    """Another character comes the other way; they stop, hop together, and the friend walks on."""

    SPEED = 14.0

    def start(self, world_x: float) -> None:
        self.fx = float(self.ctx.width + 2)
        self.stage, self.ts = "approach", self.t0
        self.last = self.t0
        self.heart = False

    def step(self, t: float, dt: float, world_x: float) -> HeroOverride | None:
        if t - self.t0 > 50:
            self.done = True
        dt = min(0.25, t - self.last)
        self.last = t
        meet_x = HOME_X + HERO_W + 2
        if self.stage == "approach":
            self.fx -= self.SPEED * dt
            if self.fx <= meet_x:
                self.fx, self.stage, self.ts = float(meet_x), "meet", t
            return None
        s = t - self.ts
        if self.stage == "meet":
            if s >= 0.8 and not self.heart:
                self.heart = True
                self.ctx.sparkles.burst(HOME_X + HERO_W + 1, GROUND_Y - 2, 14)
            if s >= 2.4:
                self.stage = "part"
                return None
            return hop(s - 0.8, 0.5, 4) if s >= 0.8 else HeroOverride(HOME_X, GROUND_Y, "stand")
        self.fx -= self.SPEED * dt
        if self.fx < -HERO_W - 1:
            self.done = True
        return None

    def world(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        poses = self.ctx.friend(phase)
        if poses is None:
            self.done = True
            return
        s = t - self.ts
        y = GROUND_Y
        if self.stage == "meet":
            if s >= 0.8:
                h = hop(s - 0.8, 0.5, 4)
                frame = poses["jump"][0 if h.pose == "jump_up" else 1]
                y = GROUND_Y - (GROUND_Y - h.y)
            else:
                frame = poses["idle"][int(t * 1.5) % 2]
        else:
            frame = poses["walk"][int(t * 6) % 4]
        img.paste(frame, (round(self.fx), y), frame)


class Dance(Moment):
    """The hero stops and dances: hops to a beat, with notes floating up."""

    def step(self, t: float, dt: float, world_x: float) -> HeroOverride | None:
        s = t - self.t0
        if s >= self.am.duration_s:
            self.done = True
            return None
        if s < 0.4:
            return HeroOverride(HOME_X, GROUND_Y, "stand")
        beat = int((s - 0.4) / 0.5)
        if beat % 2 == 0:
            if beat != getattr(self, "_beat", -1):
                self._beat = beat
                self.ctx.sparkles.burst(HOME_X + 8, GROUND_Y + 1, 3)
            return hop(s - 0.4, 0.5, 4)
        return HeroOverride(HOME_X, GROUND_Y, "stand")

    def front(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        s = t - self.t0
        if s < 0.6 or s > self.am.duration_s - 0.3:
            return
        frames = self.ctx.sprites.get("note", phase)
        for i in range(3):
            y = 36 - round((s * 7 + i * 6) % 18)
            x = HOME_X + 14 + i * 5 + round(2 * math.sin(s * 2 + i))
            f = frames[(int(s * 3) + i) % 2]
            img.paste(f, (x, y), f)


FACTORIES: dict[str, Callable[[Context, ActiveMoment, float], Moment]] = {
    **{name: Crosser for name in CROSSERS},
    "bats": Bats,
    "rainbow": Rainbow,
    "meteors": Meteors,
    "aurora": Aurora,
    "fireworks": Fireworks,
    "sandstorm": Sandstorm,
    "hall_storm": HallStorm,
    "red_alert": RedAlert,
    "cave_glow": CaveGlow,
    "chest": Chest,
    "friend": Friend,
    "dance": Dance,
}


class MomentPlayer:
    """Owns the moment that is playing. The renderer calls step, sky, world and front each frame."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._m: Moment | None = None

    @property
    def active(self) -> bool:
        return self._m is not None

    @property
    def done(self) -> bool:
        return self._m is not None and self._m.done

    def begin(self, am: ActiveMoment, world_x: float) -> None:
        self._m = FACTORIES[am.name](self.ctx, am, world_x)

    def clear(self) -> None:
        self._m = None

    def step(self, t: float, dt: float, world_x: float) -> HeroOverride | None:
        return self._m.step(t, dt, world_x) if self._m is not None else None

    def sky(self, img: Image.Image, t: float, phase: Phase) -> None:
        if self._m is not None:
            self._m.sky(img, t, phase)

    def world(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        if self._m is not None:
            self._m.world(img, t, world_x, phase)

    def front(self, img: Image.Image, t: float, world_x: float, phase: Phase) -> None:
        if self._m is not None:
            self._m.front(img, t, world_x, phase)
