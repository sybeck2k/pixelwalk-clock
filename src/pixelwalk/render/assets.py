"""Text-grid asset loading (spec section 14). One character per pixel, one palette.

File format (assets/src/*.txt):
    sprite NAME WxH [flags]     flags: ground (feet on last row), glyphs (font: pairwise distinct)
    frame [label]               followed by exactly H rows of exactly W characters
Lines starting with '#' and blank lines are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image


class AssetError(Exception):
    pass


@dataclass
class Sprite:
    name: str
    width: int
    height: int
    flags: set[str]
    frames: list[Image.Image] = field(default_factory=list)  # RGBA, alpha 0 or 255 only
    labels: list[str] = field(default_factory=list)
    source: str = ""

    def frame(self, label: str) -> Image.Image:
        return self.frames[self.labels.index(label)]


def load_palette(path: Path) -> dict[str, tuple[int, int, int]]:
    pal: dict[str, tuple[int, int, int]] = {}
    for n, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3 or len(parts[0]) != 1 or not parts[2].startswith("#") or len(parts[2]) != 7:
            raise AssetError(f"{path}:{n}: expected 'char name #rrggbb'")
        ch, _, hexcol = parts
        if ch == ".":
            raise AssetError(f"{path}:{n}: '.' is reserved for transparent")
        if ch in pal:
            raise AssetError(f"{path}:{n}: duplicate palette char {ch!r}")
        pal[ch] = tuple(int(hexcol[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[assignment]
    return pal


def _make_frame(rows: list[str], w: int, h: int, pal: dict, where: str) -> Image.Image:
    if len(rows) != h:
        raise AssetError(f"{where}: frame has {len(rows)} rows, expected {h}")
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y, row in enumerate(rows):
        if len(row) != w:
            raise AssetError(f"{where}: row {y} has {len(row)} chars, expected {w}: {row!r}")
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            if ch not in pal:
                raise AssetError(f"{where}: row {y} col {x}: char {ch!r} is not in the palette")
            px[x, y] = (*pal[ch], 255)
    return img


def parse_sprites(path: Path, pal: dict) -> list[Sprite]:
    sprites: list[Sprite] = []
    cur: Sprite | None = None
    rows: list[str] | None = None
    start = 0

    def close_frame() -> None:
        nonlocal rows
        if cur is not None and rows is not None:
            where = f"{path.name}:{start} ({cur.name}/{cur.labels[-1]})"
            cur.frames.append(_make_frame(rows, cur.width, cur.height, pal, where))
        rows = None

    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        head = line.split()
        if head[0] == "sprite":
            close_frame()
            try:
                w, h = (int(v) for v in head[2].lower().split("x"))
            except (IndexError, ValueError):
                raise AssetError(f"{path.name}:{n}: expected 'sprite NAME WxH [flags]'") from None
            cur = Sprite(head[1], w, h, set(head[3:]), source=path.name)
            sprites.append(cur)
        elif head[0] == "frame" and len(head) <= 2 and cur is not None:
            close_frame()
            cur.labels.append(head[1] if len(head) == 2 else str(len(cur.labels)))
            rows, start = [], n
        elif rows is not None:
            rows.append(line)
        else:
            raise AssetError(f"{path.name}:{n}: unexpected line outside a frame: {line!r}")
    close_frame()
    for s in sprites:
        if not s.frames:
            raise AssetError(f"{path.name}: sprite {s.name} has no frames")
    return sprites


@dataclass
class Assets:
    palette: dict[str, tuple[int, int, int]]
    sprites: dict[str, Sprite]

    def __getitem__(self, name: str) -> Sprite:
        return self.sprites[name]


def load_assets(src_dir: Path) -> Assets:
    pal = load_palette(src_dir / "palette.txt")
    sprites: dict[str, Sprite] = {}
    for f in sorted(src_dir.glob("*.txt")):
        if f.name == "palette.txt":
            continue
        for s in parse_sprites(f, pal):
            if s.name in sprites:
                raise AssetError(f"{f.name}: sprite name {s.name!r} defined twice")
            sprites[s.name] = s
    return Assets(pal, sprites)
