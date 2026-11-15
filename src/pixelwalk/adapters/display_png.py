"""In-memory (and optionally on-disk) display for tests and tools."""

from pathlib import Path

from PIL import Image


class PngDisplay:
    def __init__(self, width: int = 64, height: int = 64, out_dir: Path | None = None) -> None:
        self.width, self.height = width, height
        self.frames: list[Image.Image] = []
        self.brightness = 100
        self.out_dir = out_dir
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)

    def show(self, frame: Image.Image) -> None:
        if frame.size != (self.width, self.height) or frame.mode != "RGB":
            raise ValueError(f"frame must be RGB {self.width}x{self.height}, got {frame.mode} {frame.size}")
        copy = frame.copy()
        self.frames.append(copy)
        if self.out_dir:
            copy.save(self.out_dir / f"frame_{len(self.frames):05d}.png")

    def set_brightness(self, percent: int) -> None:
        self.brightness = percent

    def close(self) -> None:
        pass
