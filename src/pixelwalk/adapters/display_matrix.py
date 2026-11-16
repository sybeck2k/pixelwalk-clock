"""Display backed by the real panel through hzeller's rpi-rgb-led-matrix bindings (spec 5.2).

`rgbmatrix` is imported only here, and only when a MatrixDisplay is created, so everything else
imports cleanly on a PC. Create this object AFTER the motion GPIO line is opened and all assets
are loaded: once the matrix starts, the process may drop root and lose access to /dev/gpiochip0.
"""

from __future__ import annotations

import time
from typing import Any

from PIL import Image

VALID_ROTATIONS = (0, 90, 180, 270)
# Set from the named arguments, not from `options`: the app is built around one 64x64 panel.
RESERVED_OPTIONS = ("rows", "cols", "chain_length", "parallel", "hardware_mapping", "gpio_slowdown",
                    "pixel_mapper_config", "show_refresh_rate")


class MatrixDisplay:
    def __init__(
        self,
        rows: int = 64,
        cols: int = 64,
        hardware_mapping: str = "regular",
        gpio_slowdown: int = 2,
        rotation: int = 270,
        show_refresh_rate: bool = False,
        options: dict[str, Any] | None = None,
    ) -> None:
        if rotation not in VALID_ROTATIONS:
            raise ValueError(f"rotation must be one of {VALID_ROTATIONS}, got {rotation!r}")
        try:
            from rgbmatrix import RGBMatrix, RGBMatrixOptions
        except ImportError as e:
            raise RuntimeError(
                "display.backend = 'matrix' needs the rgbmatrix Python bindings from "
                "https://github.com/hzeller/rpi-rgb-led-matrix (bindings/python). "
                "On a PC use display.backend = 'emulator' instead."
            ) from e

        opts = RGBMatrixOptions()
        opts.rows = rows
        opts.cols = cols
        opts.chain_length = 1
        opts.parallel = 1
        opts.hardware_mapping = hardware_mapping
        opts.gpio_slowdown = gpio_slowdown
        # Rotation lives here and nowhere else: the rest of the app draws an upright frame.
        opts.pixel_mapper_config = f"Rotate:{rotation}" if rotation else ""
        # The library prints its refresh counter to stdout; our own output stays on stderr.
        opts.show_refresh_rate = bool(show_refresh_rate)
        # Any other RGBMatrixOptions field (pwm_bits, led_rgb_sequence, multiplexing, panel_type,
        # row_address_type, limit_refresh_rate_hz, disable_hardware_pulsing ...), by name. Looking the
        # name up on the options object keeps this working across library versions.
        for name, value in (options or {}).items():
            if name in RESERVED_OPTIONS or not hasattr(opts, name):
                raise ValueError(f"display.matrix.{name}: not a setting of this rgbmatrix library")
            setattr(opts, name, value)
        self.width, self.height = cols, rows
        self._matrix = RGBMatrix(options=opts)
        self._canvas = self._matrix.CreateFrameCanvas()
        self._brightness = 100
        # Timing of the last show(), so tools can tell work from the (idle) vsync wait.
        self.last_push_s = 0.0  # SetImage / Clear: the real work
        self.last_swap_s = 0.0  # SwapOnVSync: blocks until the panel finishes a refresh

    def show(self, frame: Image.Image) -> None:
        if frame.size != (self.width, self.height) or frame.mode != "RGB":
            raise ValueError(f"frame must be RGB {self.width}x{self.height}, got {frame.mode} {frame.size}")
        t0 = time.perf_counter()
        if self._brightness <= 0:
            # The library's minimum brightness is 1, so "dark" means a cleared canvas.
            self._canvas.Clear()
        else:
            # Brightness only affects pixels set afterwards, so set it before SetImage.
            self._set_canvas_brightness(self._brightness)
            self._canvas.SetImage(frame)
        t1 = time.perf_counter()
        self._canvas = self._matrix.SwapOnVSync(self._canvas)
        self.last_push_s = t1 - t0
        self.last_swap_s = time.perf_counter() - t1

    def _set_canvas_brightness(self, percent: int) -> None:
        try:
            self._canvas.brightness = percent
        except AttributeError:  # an older library: brightness is a property of the matrix only
            self._matrix.brightness = percent

    def set_brightness(self, percent: int) -> None:
        self._brightness = max(0, min(100, int(percent)))

    def close(self) -> None:
        self._matrix.Clear()
