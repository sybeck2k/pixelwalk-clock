import sys
import types
from pathlib import Path
from typing import ClassVar

import pytest
from PIL import Image

from pixelwalk.app import build_app
from pixelwalk.config import load_config
from pixelwalk.tools.benchmark import report, run, summarize
from pixelwalk.tools.led_preview import (
    cie_luminance,
    collapsed_pairs,
    display_table,
    led_preview,
    pwm_count,
)

ROOT = Path(__file__).resolve().parents[2]


# --- MatrixDisplay against a fake rgbmatrix ---------------------------------------------


class FakeCanvas:
    def __init__(self, log):
        self.log = log
        self._brightness = 100

    @property
    def brightness(self):
        return self._brightness

    @brightness.setter
    def brightness(self, v):
        self._brightness = v
        self.log.append(("brightness", v))

    def SetImage(self, img):
        self.log.append(("SetImage", img.size))

    def Clear(self):
        self.log.append(("Clear",))


class FakeMatrix:
    last_options = None
    log: ClassVar[list] = []

    def __init__(self, options):
        FakeMatrix.last_options = options
        self.canvas = FakeCanvas(FakeMatrix.log)

    def CreateFrameCanvas(self):
        return self.canvas

    def SwapOnVSync(self, canvas):
        FakeMatrix.log.append(("Swap",))
        return canvas

    def Clear(self):
        FakeMatrix.log.append(("MatrixClear",))


class FakeOptions:
    pass


@pytest.fixture
def fake_rgbmatrix(monkeypatch):
    mod = types.ModuleType("rgbmatrix")
    mod.RGBMatrix = FakeMatrix
    mod.RGBMatrixOptions = FakeOptions
    monkeypatch.setitem(sys.modules, "rgbmatrix", mod)
    FakeMatrix.log = []
    return FakeMatrix


def frame():
    return Image.new("RGB", (64, 64), (10, 20, 30))


def test_matrix_options_and_rotation(fake_rgbmatrix):
    from pixelwalk.adapters.display_matrix import MatrixDisplay

    MatrixDisplay(rows=64, cols=64, hardware_mapping="regular", gpio_slowdown=2, rotation=270)
    o = fake_rgbmatrix.last_options
    assert (o.rows, o.cols, o.chain_length, o.parallel) == (64, 64, 1, 1)
    assert (o.hardware_mapping, o.gpio_slowdown, o.pixel_mapper_config) == ("regular", 2, "Rotate:270")
    assert o.show_refresh_rate is False
    MatrixDisplay(rotation=0)
    assert fake_rgbmatrix.last_options.pixel_mapper_config == ""  # no mapper for 0
    with pytest.raises(ValueError, match="rotation"):
        MatrixDisplay(rotation=45)


def test_brightness_is_set_before_the_image(fake_rgbmatrix):
    from pixelwalk.adapters.display_matrix import MatrixDisplay

    d = MatrixDisplay()
    d.set_brightness(40)
    fake_rgbmatrix.log.clear()
    d.show(frame())
    assert fake_rgbmatrix.log == [("brightness", 40), ("SetImage", (64, 64)), ("Swap",)]


def test_brightness_zero_clears_instead_of_drawing(fake_rgbmatrix):
    from pixelwalk.adapters.display_matrix import MatrixDisplay

    d = MatrixDisplay()
    d.set_brightness(0)
    fake_rgbmatrix.log.clear()
    d.show(frame())
    assert fake_rgbmatrix.log == [("Clear",), ("Swap",)]
    d.set_brightness(150)  # clamped
    assert d._brightness == 100


def test_matrix_rejects_bad_frames_and_close_clears(fake_rgbmatrix):
    from pixelwalk.adapters.display_matrix import MatrixDisplay

    d = MatrixDisplay()
    with pytest.raises(ValueError):
        d.show(Image.new("RGB", (32, 32)))
    with pytest.raises(ValueError):
        d.show(Image.new("RGBA", (64, 64)))
    d.close()
    assert ("MatrixClear",) in fake_rgbmatrix.log


def test_rgbmatrix_is_not_imported_on_the_pc():
    assert "rgbmatrix" not in sys.modules or isinstance(sys.modules["rgbmatrix"], types.ModuleType)
    import pixelwalk.adapters.display_matrix  # noqa: F401  must import without rgbmatrix


# --- app wiring -------------------------------------------------------------------------


def test_pi_check_profile_loads_real_display_and_clock_with_sim_inputs():
    cfg = load_config(ROOT / "config", "pi-check")
    assert cfg["display"]["backend"] == "matrix" and cfg["clock"]["backend"] == "system"
    assert cfg["sensors"]["backend"] == cfg["motion"]["backend"] == cfg["weather"]["backend"] == "sim"


def test_assets_load_before_the_matrix_is_created(monkeypatch, fake_rgbmatrix):
    order = []
    import pixelwalk.app as app_mod

    real_renderer = app_mod.Renderer

    class SpyRenderer(real_renderer):
        def __init__(self, *a, **k):
            order.append("assets")
            super().__init__(*a, **k)

    monkeypatch.setattr(app_mod, "Renderer", SpyRenderer)
    orig_init = FakeMatrix.__init__

    def spy_init(self, options):
        order.append("matrix")
        orig_init(self, options)

    monkeypatch.setattr(FakeMatrix, "__init__", spy_init)
    cfg = load_config(ROOT / "config", "pi-check")
    app = build_app(cfg, ROOT)
    assert order == ["assets", "matrix"]
    assert app.target_fps == 30.0


# --- benchmark --------------------------------------------------------------------------


def test_summarize_median_p99_max():
    assert summarize([1, 2, 3]) == (2, 3, 3)
    assert summarize([1, 2, 3, 4]) == (2.5, 4, 4)
    values = list(range(1, 101))
    assert summarize(values) == (50.5, 99, 100)


def test_benchmark_run_counts_late_frames_and_reports_verdict():
    from pixelwalk.render.renderer import Renderer

    r = Renderer(ROOT / "assets" / "src")
    ticks = iter(range(10_000))
    fake_now = lambda: next(ticks) * 0.001

    class SlowDisplay:
        def show(self, img):
            pass

    result = run(r, "2026-07-01 12:00:00", 20, SlowDisplay(), fps=500, sleep=lambda s: None, perf=fake_now)
    assert result["frames"] == 20 and result["show"] is not None
    text = report(result)
    assert "compose" in text and "show" in text and "budget" in text
    fast = run(r, "2026-07-01 12:00:00", 5)
    assert fast["show"] is None and "PASS" in report(fast)


# --- LED model --------------------------------------------------------------------------


def test_cie_model_matches_library_formula():
    assert cie_luminance(0, 100) == 0 and cie_luminance(255, 100) == pytest.approx(1.0)
    assert cie_luminance(255, 0) == 0
    assert cie_luminance(255, 10) == pytest.approx(((10 + 16) / 116) ** 3)  # above the L<=8 knee
    assert cie_luminance(60, 10) == pytest.approx((60 / 255 * 10) / 902.3)  # linear segment
    assert pwm_count(255, 100) == 2047


def test_low_brightness_has_few_levels():
    levels = {pwm_count(c, 10) for c in range(256)}
    assert 15 < len(levels) < 40  # the reason night palettes need well-separated colours
    assert len({pwm_count(c, 100) for c in range(256)}) >= 250  # nearly every input is distinct


def test_display_table_is_monotonic_and_dimmer_at_low_brightness():
    full, dim = display_table(100), display_table(10)
    assert full == sorted(full) and dim == sorted(dim)
    assert full[255] == 255 and dim[255] < 120 and dim[0] == 0


def test_collapsed_pairs_flags_close_colours_only():
    img = Image.new("RGB", (8, 8), (46, 40, 68))
    img.paste((61, 50, 73), (0, 0, 8, 4))  # a long edge of two close dark colours
    assert collapsed_pairs(img, 100) == []  # fine at full brightness
    bad = collapsed_pairs(img, 10)
    assert len(bad) == 1 and bad[0][2] == 8
    img.paste((255, 255, 255), (0, 0, 8, 4))
    assert collapsed_pairs(img, 10) == []  # clearly different colours stay distinguishable


def test_led_preview_is_dots_on_black():
    out = led_preview(Image.new("RGB", (4, 4), (255, 255, 255)), 100, scale=8)
    assert out.size == (32, 32)
    assert out.getpixel((4, 4)) == (255, 255, 255)  # centre of a dot
    assert out.getpixel((0, 0)) == (0, 0, 0)  # corner of the cell is the gap


def test_shipped_palettes_do_not_collapse_at_night_and_10_percent():
    from datetime import timedelta

    from pixelwalk.adapters.scenario import parse_start
    from pixelwalk.render.renderer import Renderer

    r = Renderer(ROOT / "assets" / "src")
    for when in ("2026-07-01 23:00", "2026-07-01 02:00", "2026-07-01 20:30"):
        f = r.render(
            __import__("pixelwalk.state", fromlist=["WorldSnapshot"]).WorldSnapshot(),
            0.0,
            parse_start(when) + timedelta(0),
        ).copy()
        assert collapsed_pairs(f, 10) == [], when


def test_benchmark_budget_uses_work_not_the_vsync_wait():
    from pixelwalk.render.renderer import Renderer

    class VsyncDisplay:
        """Like MatrixDisplay: tiny push, then a long blocking wait for the panel refresh."""

        last_push_s = 0.0015
        last_swap_s = 0.0095

        def show(self, img):
            pass

    r = Renderer(ROOT / "assets" / "src")
    ticks = iter(range(100_000))
    # Each perf() call advances 6 ms, so compose and total look slow, but push is 1.5 ms.
    result = run(r, "2026-07-01 12:00:00", 10, VsyncDisplay(), fps=30, sleep=lambda s: None,
                 perf=lambda: next(ticks) * 0.006)
    assert result["push"] is not None and result["vsync wait"] is not None
    assert result["push"][0] == pytest.approx(1.5) and result["vsync wait"][0] == pytest.approx(9.5)
    # work = compose (6 ms) + push (1.5 ms) = 7.5 ms, even though show() took 6 ms and total 12 ms
    assert result["work"][0] == pytest.approx(7.5)
    assert "vsync wait" in report(result)
    assert "work (compose + push)" in report(result)
    assert "PASS" in report(result)  # 7.5 ms < 10 ms, and no frame later than its 33 ms period
