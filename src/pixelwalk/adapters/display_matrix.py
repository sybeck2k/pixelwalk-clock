"""Display backed by the real panel through hzeller's rpi-rgb-led-matrix bindings (spec 5.2).

`rgbmatrix` is imported only here, and only when a MatrixDisplay is created, so everything else
imports cleanly on a PC. Create this object AFTER the motion GPIO line is opened and all assets
are loaded: once the matrix starts, the process may drop root and lose access to /dev/gpiochip0.
"""

from __future__ import annotations

from PIL import Image

VALID_ROTATIONS = (0, 90, 180, 270)


class MatrixDisplay:
    def __init__(
        self,
        rows: int = 64,
        cols: int = 64,
        hardware_mapping: str = "regular",
        gpio_slowdown: int = 2,
        rotation: int = 270,
        show_refresh_rate: bool = False,
    ) -> None:
        if rotation not in VALID_ROTATIONS:
            raise ValueError(f"rotation must be one of {VALID_ROTATIONS}, got {rotation!r}")
        from rgbmatrix import RGBMatrix, RGBMatrixOptions

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
        self.width, self.height = cols, rows
        self._matrix = RGBMatrix(options=opts)
        self._canvas = self._matrix.CreateFrameCanvas()
        self._brightness = 100

    def show(self, frame: Image.Image) -> None:
        if frame.size != (self.width, self.height) or frame.mode != "RGB":
            raise ValueError(f"frame must be RGB {self.width}x{self.height}, got {frame.mode} {frame.size}")
        if self._brightness <= 0:
            # The library's minimum brightness is 1, so "dark" means a cleared canvas.
            self._canvas.Clear()
        else:
            # Brightness only affects pixels set afterwards, so set it before SetImage.
            self._canvas.brightness = self._brightness
            self._canvas.SetImage(frame)
        self._canvas = self._matrix.SwapOnVSync(self._canvas)

    def set_brightness(self, percent: int) -> None:
        self._brightness = max(0, min(100, int(percent)))

    def close(self) -> None:
        self._matrix.Clear()
