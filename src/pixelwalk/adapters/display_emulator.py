"""Display backed by RGBMatrixEmulator (browser page on port 8888).

Phase-1 finding: the emulator's canvas supports SetImage (paste) and brightness
(applied at draw time, 0..100), so no workarounds are needed here.
"""

from PIL import Image


class EmulatorDisplay:
    def __init__(self, rows: int = 64, cols: int = 64) -> None:
        from RGBMatrixEmulator import RGBMatrix, RGBMatrixOptions

        opts = RGBMatrixOptions()
        opts.rows = rows
        opts.cols = cols
        self.width, self.height = cols, rows
        self._matrix = RGBMatrix(options=opts)
        self._canvas = self._matrix.CreateFrameCanvas()

    def show(self, frame: Image.Image) -> None:
        if frame.size != (self.width, self.height) or frame.mode != "RGB":
            raise ValueError(f"frame must be RGB {self.width}x{self.height}, got {frame.mode} {frame.size}")
        self._canvas.SetImage(frame)
        self._canvas = self._matrix.SwapOnVSync(self._canvas)

    def set_brightness(self, percent: int) -> None:
        self._canvas.brightness = max(0, min(100, int(percent)))

    def close(self) -> None:
        pass
