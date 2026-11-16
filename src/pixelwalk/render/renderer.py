"""Frame composition (spec 7.1, 7.2).

Back to front: sky, sky wash, stars/sun/moon, clouds, far and near strips, ground, hero (+ umbrella
or scarf), transition pipe, rain/snow/wind, fog, scene dimming, lightning, clock blocks, wipe.
(The pipe is drawn after the hero so the hero can sink into it.)

Only Pillow calls per frame (pastes with masks, cached blends and masks); no per-pixel Python
loops over the frame, no resampling.
"""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps

from ..logic.astro import (
    Phase,
    PhaseBlend,
    arc_position,
    moon_phase_index,
    moon_progress,
    phase_blend,
    seconds_of_day,
    star_level,
    sun_progress,
    valid_sun_times,
)
from ..logic.clockface import GROUND_Y, HOME_X, ClockFace, HeroOverride
from ..logic.director import Biome, BiomeSelector, effect_target, hero_accessory
from ..logic.effects import EffectState
from ..logic.events import (
    STYLES,
    EventScheduler,
    active_styles,
    parse_events_config,
)
from ..logic.hero import Hero
from ..logic.presence import PresenceState
from ..logic.transition import Transition
from ..state import WorldSnapshot
from .assets import Assets, load_assets
from .events import Sparkles, bird_position, draw_lights, draw_props, draw_shooting_star
from .hud import Hud, format_temp
from .particles import Clouds, Lightning, Rain, Snow, Wind
from .phases import phase_palette, remap_image
from .world import BIOMES, FADE_STEPS, World

BLOCK_Y = 8
BLOCK_X = {"hh": 11, "mm": 34}
DIGIT_W, DIGIT_H, DIGIT_GAP = 5, 7, 1
DIGIT_DX = (19 - (2 * DIGIT_W + DIGIT_GAP)) // 2  # 4
DIGIT_DY = (13 - DIGIT_H) // 2  # 3
INK = (0, 0, 0)

STAR_COUNT = 30
STAR_AREA_H = 30  # stars live above the hills
STAR_LEVELS = 8
TWINKLE_STARS = 6
TWINKLE_PERIOD = 0.8

SKY_H = 40  # the sky wash covers the sky down to the horizon
FOG_TOP = 22  # the fog wash covers the scenery, not the clock blocks' band
PIPE_Y = 40

CAMP_X, CAMP_Y = 44, 46  # the campfire the robot rests beside (8x10, on the ground line)
SLEEP_AFTER_S = 20.0  # drowsy: sits awake for this long, then sleeps
WALK_SPEED = 8.0  # px/s: the campfire drifts away with the ground once the robot walks on
HUD_Y = 1

DEFAULT_SUNRISE_S = 7 * 3600 + 30 * 60
DEFAULT_SUNSET_S = 18 * 3600 + 30 * 60

# Wash colours per phase: the sky wash for overcast weather, and fog.
SKY_WASH = {Phase.DAY: (140, 148, 160), Phase.DAWN: (120, 100, 110), Phase.DUSK: (110, 90, 105), Phase.NIGHT: (14, 18, 30)}
FOG_WASH = {Phase.DAY: (205, 210, 220), Phase.DAWN: (200, 175, 180), Phase.DUSK: (190, 160, 170), Phase.NIGHT: (40, 46, 64)}


# Dimming and fog compress contrast, which an already dark night scene cannot afford (the panel
# has only ~23 brightness levels at 10%), so they are gentler at night.
NIGHT_SOFTEN = {Phase.DAY: 1.0, Phase.DAWN: 1.0, Phase.DUSK: 0.9, Phase.NIGHT: 0.35}


def _mix(a: tuple, b: tuple, t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))  # type: ignore[return-value]


def build_star_images(assets: Assets, width: int, rng: random.Random) -> list[list[Image.Image]]:
    """images[level][twinkle_variant]: one RGBA layer whose alpha is the star brightness."""
    colours = [assets.palette[c] for c in "wwwwwyc"]
    stars = [(rng.randrange(width), rng.randrange(STAR_AREA_H), rng.choice(colours)) for _ in range(STAR_COUNT)]
    out: list[list[Image.Image]] = []
    for level in range(STAR_LEVELS + 1):
        alpha = level * 255 // STAR_LEVELS
        variants = []
        for variant in (0, 1):
            img = Image.new("RGBA", (width, STAR_AREA_H), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            for i, (x, y, col) in enumerate(stars):
                if variant == 1 and i < TWINKLE_STARS:
                    continue
                d.point((x, y), fill=(*col, alpha))
            variants.append(img)
        out.append(variants)
    return out


class Renderer:
    def __init__(
        self,
        assets_dir: Path,
        width: int = 64,
        height: int = 64,
        seed: int = 1,
        hour24: bool = True,
        assets: Assets | None = None,
        sunrise_s: float = DEFAULT_SUNRISE_S,
        sunset_s: float = DEFAULT_SUNSET_S,
        min_stay_s: float = 600.0,
        hud_indoor: bool = True,
        hud_outdoor: bool = True,
        cold_c: float = 18.0,
        hot_c: float = 26.0,
        events: dict | None = None,
    ) -> None:
        self.width, self.height = width, height
        self.assets = assets or load_assets(assets_dir)
        self.fallback_sun = (sunrise_s, sunset_s)
        self.world = World(self.assets, seed, width, height)
        rng = random.Random(seed)
        self.hero = Hero(rng)
        self.clockface = ClockFace(hour24=hour24)
        self.selector = BiomeSelector(min_stay_s)
        self.biome = Biome.GRASS
        self._transition: Transition | None = None
        self.effects = EffectState()
        # Settings the control page can change while the app runs.
        self.hud_indoor, self.hud_outdoor, self.cold_c, self.hot_c = hud_indoor, hud_outdoor, cold_c, hot_c
        self._camp_x: float | None = None
        ev = events or {}
        self.events = EventScheduler(random.Random(seed + 7), ev.get("enabled", True), ev.get("rate", 1.0))
        self.sparkles = Sparkles(random.Random(seed + 8))
        self._dated, self._birthdays = parse_events_config(ev)
        self._styles: frozenset[str] = frozenset()
        self._styles_day = None
        self._forced_seen = ""
        self._event_seen: float | None = None
        self._coin_wx = 0.0
        self._confetti_at = 0.0

        self._stars = build_star_images(self.assets, width, random.Random(seed + 1))
        self._sun = self.assets["sun"].frames[0]
        moon = self.assets["moon"].frames  # new, waxing crescent, first quarter, waxing gibbous, full
        mirrored = [ImageOps.mirror(f) for f in (moon[3], moon[2], moon[1])]
        self._moon = [*moon, *mirrored]  # indexed by astro.moon_phase_index
        # The whole disc, lit or not: the dark side of the moon still hides the stars behind it.
        self._moon_disc = moon[4].getchannel("A")

        master = self.assets.palette
        self._pal = {p: phase_palette(master, p) for p in Phase}
        actor = {p: phase_palette(master, p, actor=True) for p in Phase}
        names = (
            "hero_walk", "hero_idle", "hero_jump", "umbrella", "scarf",
            "hero_sit", "hero_wake", "sleep_z", "campfire",
            "sweat", "bird", "coin", "pumpkin", "cake",
        )
        self._hero = {  # pre-tinted per phase, so no colour maths per frame
            p: {n: [remap_image(f, master, actor[p]) for f in self.assets[n].frames] for n in names} for p in Phase
        }
        self._pipes = {
            p: {b: remap_image(self.assets[d.pipe].frames[0], master, self._pal[p]) for b, d in BIOMES.items()}
            for p in Phase
        }
        cloud_names = ("cloud_a", "cloud_b")
        self._cloud_sizes = [(self.assets[n].width, self.assets[n].height) for n in cloud_names]
        self._cloud_imgs = {
            p: [remap_image(self.assets[n].frames[0], master, self._pal[p]) for n in cloud_names] for p in Phase
        }
        self.clouds = Clouds(random.Random(seed + 2), self._cloud_sizes, width)
        self.rain = Rain(random.Random(seed + 3), width)
        self.snow = Snow(random.Random(seed + 4), width)
        self.wind = Wind(random.Random(seed + 5), width)
        self.lightning = Lightning(random.Random(seed + 6))

        self._img = Image.new("RGB", (width, height))  # one working image, reused every frame
        self._draw = ImageDraw.Draw(self._img)
        self._white = Image.new("RGB", (width, height), (255, 255, 255))
        self._masks: dict[tuple, Image.Image] = {}
        self._scaled: dict[tuple, Image.Image] = {}
        self._cloud_blend: dict[tuple, Image.Image] = {}
        font3 = self.assets["font3x5"]
        self.hud = Hud({lab: f.getchannel("A") for lab, f in zip(font3.labels, font3.frames, strict=True)})
        self._block = self.assets["clock_block"].frames[0]
        font = self.assets["font5x7"]
        # Glyph masks: ink pixels are opaque, so the alpha channel is the paste mask.
        self._glyph = {lab: f.getchannel("A") for lab, f in zip(font.labels, font.frames, strict=True)}
        self._last_t: float | None = None

    # --- helpers --------------------------------------------------------------------------

    def _sun_times(self, snap: WorldSnapshot) -> tuple[float, float]:
        w = snap.weather
        if w is not None:
            sr, ss = seconds_of_day(w.sunrise), seconds_of_day(w.sunset)
            if valid_sun_times(sr, ss):
                return sr, ss
        return self.fallback_sun

    def _const_mask(self, size: tuple[int, int], level: float) -> Image.Image | None:
        q = round(max(0.0, min(1.0, level)) * FADE_STEPS)
        if q == 0:
            return None
        key = (size, q)
        m = self._masks.get(key)
        if m is None:
            m = self._masks[key] = Image.new("L", size, min(255, q * 255 // FADE_STEPS))
        return m

    def _wash(self, img: Image.Image, colour: tuple, box: tuple[int, int, int, int], level: float) -> None:
        mask = self._const_mask((box[2] - box[0], box[3] - box[1]), level)
        if mask is not None:
            img.paste(colour, box, mask)

    def _paste_faded(self, img: Image.Image, sprite: Image.Image, pos: tuple[int, int], level: float) -> None:
        """Paste a hard-edged sprite at partial strength (sun, moon hidden by weather)."""
        q = round(max(0.0, min(1.0, level)) * FADE_STEPS)
        if q == 0:
            return
        if q >= FADE_STEPS:
            img.paste(sprite, pos, sprite)
            return
        key = (id(sprite), q)
        m = self._scaled.get(key)
        if m is None:
            scale = Image.new("L", sprite.size, q * 255 // FADE_STEPS)
            m = self._scaled[key] = ImageChops.multiply(sprite.getchannel("A"), scale)
        img.paste(sprite, pos, m)

    def _cloud_image(self, kind: int, blend: PhaseBlend) -> Image.Image:
        a = self._cloud_imgs[blend.a][kind]
        q = round(blend.t * FADE_STEPS)
        if blend.a is blend.b or q == 0:
            return a
        b = self._cloud_imgs[blend.b][kind]
        if q >= FADE_STEPS:
            return b
        key = (kind, blend.a, blend.b, q)
        img = self._cloud_blend.get(key)
        if img is None:
            img = self._cloud_blend[key] = Image.blend(a, b, q / FADE_STEPS)
        return img

    # --- frame ----------------------------------------------------------------------------

    def render(self, snap: WorldSnapshot, t: float, now: datetime) -> Image.Image:
        """`t` is Clock.monotonic() seconds and `now` is Clock.now(); both come from the caller."""
        dt = 0.0 if self._last_t is None else min(0.25, max(0.0, t - self._last_t))
        self._last_t = t
        weather = snap.weather
        s = seconds_of_day(now)
        sunrise, sunset = self._sun_times(snap)
        blend = phase_blend(s, sunrise, sunset)
        hero_phase = blend.b if blend.t >= 0.5 else blend.a

        # Biome and transition.
        if self.selector.current is None:
            self.biome = self.selector.initialize(t, weather)
        pv = snap.presence
        active = pv is None or pv.state is PresenceState.ACTIVE  # resting: no pipe trips, no bumps
        if self._transition is None and not self.clockface.bumping and active:
            wanted = self.selector.target(t, weather)
            if wanted is not self.selector.current:
                self._transition = Transition(t, self.selector.current, wanted)
        tv = self._transition.view(t) if self._transition else None
        if tv is not None:
            if tv.biome is not self.biome:  # the screen is black: swap the scenery now
                self.biome = tv.biome
                self.selector.commit(t, tv.biome)
            if tv.done:
                self._transition, tv = None, None

        # Clock and hero.
        prev_shown = self.clockface.shown
        view = self.clockface.update(now, t, hero_available=not (tv and tv.busy) and active)
        shown = self.clockface.shown
        if self.events.enabled and prev_shown and shown and shown[0] != prev_shown[0]:
            for key in ("hh", "mm"):  # the hour change: a short burst over both blocks
                self.sparkles.burst(BLOCK_X[key] + 9, BLOCK_Y + 2, 10)
        override = tv.hero if (tv and tv.hero) else None
        sleeping = False
        if override is None and pv is not None and not active:
            if pv.state is PresenceState.WAKING:
                override = HeroOverride(HOME_X, GROUND_Y, "wake")
            else:  # DROWSY (and DARK, if it is ever drawn): sit, then sleep
                sleeping = pv.state is PresenceState.DARK or pv.since_s >= SLEEP_AFTER_S
                override = HeroOverride(HOME_X, GROUND_Y, "sleep" if sleeping else "sit")
        if override is None:
            override = view.hero
        draw = self.hero.update(t, override, force_walk=bool(tv and tv.force_walk))
        ev = self._event(snap, t, now, hero_phase, allowed=active and tv is None and not self.clockface.bumping)

        # Weather effects.
        target = effect_target(
            weather.condition if weather else None,
            weather.gust_kmh if weather else 0.0,
            weather.cloud_cover_pct if weather else 0.0,
            snap.pressure_trend,
        )
        lv = self.effects.update(dt, target)
        self.clouds.update(dt, target.clouds)
        self.rain.update(dt, lv.rain, target.slant)
        self.snow.update(dt, lv.snow)
        self.wind.update(dt, lv.leaves)

        img = self._img
        sky = self.world.draw_sky(img, self.biome, blend)
        self._celestial(img, t, now, s, sunrise, sunset, lv.clear, sky)
        self._wash(img, _mix(SKY_WASH[blend.a], SKY_WASH[blend.b], blend.t), (0, 0, self.width, SKY_H), lv.tint)
        for c in self.clouds.clouds:
            cimg = self._cloud_image(c.kind, blend)
            img.paste(cimg, (round(c.x), c.y), cimg)
        if ev is not None and ev.name == "shooting_star" and lv.clear >= 0.5:
            draw_shooting_star(self._draw, ev.progress(t), ev.seed, self._pal[hero_phase])
        far_visibility = 1.0 - min(1.0, lv.fog / 0.6)
        self.world.draw_strips(img, self.hero.world_x, self.biome, blend, far_visibility)

        sprites = self._hero[hero_phase]
        self._event_scenery(img, sprites, ev, t, dt, draw)
        sprite = sprites[draw.sprite][draw.frame]
        img.paste(sprite, (draw.x, draw.y), sprite)
        self._campfire(img, sprites, t, dt, pv, draw, sleeping)
        if tv is None and active:
            indoor = snap.sensors.temperature_c if snap.sensors is not None else None
            acc = hero_accessory(lv.rain, lv.snow, indoor_c=indoor, cold_c=self.cold_c, hot_c=self.hot_c)
            if acc == "umbrella":
                u = sprites["umbrella"][0]
                img.paste(u, (draw.x, draw.y - 3), u)
            elif acc == "scarf":
                sc = sprites["scarf"][int(t * 3) % 2]
                img.paste(sc, (draw.x, draw.y + 8), sc)
            elif acc == "sweat":
                drop = sprites["sweat"][0]  # a drop slides down the side of the head, then repeats
                img.paste(drop, (draw.x + 13, draw.y + 1 + int(t * 3) % 4), drop)
        if tv is not None and tv.pipe_x is not None and tv.pipe_biome is not None:
            pipe = self._pipes[hero_phase][tv.pipe_biome]
            img.paste(pipe, (tv.pipe_x, PIPE_Y), pipe)

        self._particles(img, hero_phase, target.slant)
        fog_colour = _mix(FOG_WASH[blend.a], FOG_WASH[blend.b], blend.t)
        soften = NIGHT_SOFTEN[blend.a] + (NIGHT_SOFTEN[blend.b] - NIGHT_SOFTEN[blend.a]) * blend.t
        fog = lv.fog * (0.4 + 0.6 * soften)
        self._wash(img, fog_colour, (0, FOG_TOP - 4, self.width, FOG_TOP), fog * 0.45)  # a soft top edge
        self._wash(img, fog_colour, (0, FOG_TOP, self.width, self.height), fog)
        self._wash(img, (0, 0, 0), (0, 0, self.width, self.height), lv.dim * soften)
        flash = self.lightning.level(t, target.lightning)
        if flash:
            img.paste(Image.blend(img, self._white, flash))

        self._block_with_digits(img, "hh", view.hh, view.hh_dy)
        self._block_with_digits(img, "mm", view.mm, view.mm_dy)
        self.sparkles.update(dt)
        self.sparkles.draw(self._draw, self._pal[hero_phase])
        self._status_row(img, snap, hero_phase)
        if "lights" in self._styles:
            draw_lights(self._draw, t, self.width, self.assets.palette)  # untinted: bulbs glow at night
        if tv is not None and tv.wipe is not None:
            kind, w = tv.wipe
            box = (0, 0, w, self.height) if kind == "close" else (w, 0, self.width, self.height)
            if box[2] > box[0]:
                img.paste((0, 0, 0), box)
        return img

    def _event(self, snap: WorldSnapshot, t: float, now: datetime, phase: Phase, allowed: bool):
        """The random event playing now (or None), and which dated styles are on today."""
        forced = snap.forced_event
        day = (now.date(), forced, self.events.enabled)
        if day != self._styles_day:
            self._styles_day = day
            styles = set(active_styles(now.date(), self._dated, self._birthdays)) if self.events.enabled else set()
            if forced in STYLES:
                styles.add(forced)
            self._styles = frozenset(styles)
        if forced != self._forced_seen:
            self._forced_seen = forced
            if forced and self.events.enabled:
                self.events.trigger(forced, t)
        ev = self.events.update(t, phase, allowed, walking=self.hero.walking)
        if ev is not None and ev.start != self._event_seen:
            self._event_seen = ev.start
            if ev.name == "coin":  # it sits in the world ahead of the robot and scrolls toward it
                self._coin_wx = self.hero.world_x + self.width + 6
        return ev

    def _event_scenery(self, img, sprites, ev, t: float, dt: float, draw) -> None:
        """Things that stand in the scene behind the robot: a bird, the coin, pumpkins, the cake."""
        if ev is not None and ev.name == "bird":
            x, y = bird_position(ev.progress(t), ev.seed, self.width)
            bird = sprites["bird"][int(t * 6) % 2]
            img.paste(bird, (x, y), bird)
        elif ev is not None and ev.name == "coin":
            x = round(self._coin_wx - self.hero.world_x)
            y = GROUND_Y + 4 + round(1.5 * ((t * 2) % 2 - 1) ** 2)
            coin = sprites["coin"][int(t * 4) % 2]
            img.paste(coin, (x, y), coin)
            if x <= draw.x + 8:  # picked up
                self.sparkles.burst(x + 2, y + 2, 12)
                self.events.finish(t)
        if "pumpkins" in self._styles:
            draw_props(img, sprites["pumpkin"][int(t * 2) % 2], self.hero.world_x, 80, GROUND_Y + 16)
        if "cake" in self._styles:
            pos = draw_props(img, sprites["cake"][int(t * 4) % 2], self.hero.world_x, 130, GROUND_Y + 16)
            if pos is not None and t >= self._confetti_at:
                self.sparkles.burst(pos[0] + 5, pos[1], 4)
                self._confetti_at = t + 0.8

    def _campfire(self, img, sprites, t, dt, pv, draw, sleeping) -> None:
        resting = pv is not None and pv.state in (PresenceState.DROWSY, PresenceState.WAKING, PresenceState.DARK)
        if resting:
            self._camp_x = float(CAMP_X)
        elif self._camp_x is not None:  # the robot has walked on: the fire slides away with the ground
            self._camp_x -= WALK_SPEED * dt
            if self._camp_x < -8:
                self._camp_x = None
        if self._camp_x is not None:
            fire = sprites["campfire"][int(t * 6) % 3]
            img.paste(fire, (round(self._camp_x), CAMP_Y), fire)
        if sleeping:  # a floating z above the sleeping robot
            z = sprites["sleep_z"][int(t * 1.5) % 2]
            img.paste(z, (draw.x + 8, draw.y - 5), z)

    def _status_row(self, img: Image.Image, snap: WorldSnapshot, phase: Phase) -> None:
        pal = self._pal[phase]
        if self.hud_indoor and snap.sensors is not None and snap.sensors.temperature_c is not None:
            c = snap.sensors.temperature_c
            colour = pal["c"] if c < self.cold_c else pal["B"] if c > self.hot_c else pal["w"]
            text = self.hud.image(format_temp(c), colour)
            img.paste(text, (1, HUD_Y), text)
        if self.hud_outdoor and snap.weather is not None:
            text = self.hud.image(format_temp(snap.weather.temperature_c), pal["w"])
            img.paste(text, (self.width - text.width - 1, HUD_Y), text)

    def _celestial(
        self,
        img: Image.Image,
        t: float,
        now: datetime,
        s: float,
        sunrise: float,
        sunset: float,
        clear: float,
        sky: Image.Image,
    ) -> None:
        level = round(star_level(s, sunrise, sunset) * clear * STAR_LEVELS)
        if level:
            layer = self._stars[level][int(t / TWINKLE_PERIOD) % 2]
            img.paste(layer, (0, 0), layer)
        p = sun_progress(s, sunrise, sunset)
        if p is not None:
            self._paste_faded(img, self._sun, arc_position(p, self.width), clear)
        p = moon_progress(s, sunrise, sunset)
        if p is not None:
            x, y = arc_position(p, self.width)
            if level:  # put the bare sky back inside the whole disc: the unlit side hides the stars
                size = self._moon_disc.size
                img.paste(sky.crop((x, y, x + size[0], y + size[1])), (x, y), self._moon_disc)
            self._paste_faded(img, self._moon[moon_phase_index(now)], (x, y), clear)

    def _particles(self, img: Image.Image, phase: Phase, slant: bool) -> None:
        pal = self._pal[phase]
        d = self._draw
        if self.rain.xs:
            colour = pal["c"] if phase is Phase.NIGHT else pal["u"]
            self.rain.draw(d, colour, pal["w"], slant)
        if self.snow.x0:
            self.snow.draw(d, pal["w"])
        if self.wind.items:
            kind = BIOMES[self.biome].wind
            colours = {
                "leaves": (pal["g"], pal["B"]),
                "sand": (pal["N"], pal["Y"]),  # darker than the dunes, so the streaks show
                "snow": (pal["w"], pal["a"]),
            }[kind]
            self.wind.draw(d, kind, colours)

    def _block_with_digits(self, img: Image.Image, which: str, text: str, dy: int) -> None:
        x, y = BLOCK_X[which], BLOCK_Y + dy
        img.paste(self._block, (x, y), self._block)
        for i, ch in enumerate(text):
            mask = self._glyph.get(ch)
            if mask is None:
                if ch == "-":  # "--" placeholder: a 3 px bar mid-glyph
                    gx = x + DIGIT_DX + i * (DIGIT_W + DIGIT_GAP) + 1
                    img.paste(INK, (gx, y + DIGIT_DY + 3, gx + 3, y + DIGIT_DY + 4))
                continue
            gx = x + DIGIT_DX + i * (DIGIT_W + DIGIT_GAP)
            img.paste(INK, (gx, y + DIGIT_DY), mask)
