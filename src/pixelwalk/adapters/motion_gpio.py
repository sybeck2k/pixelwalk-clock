"""PIR motion input on a GPIO line, read with libgpiod (spec 5.4).

The level is read, not edges, a few times a second from a background thread, so nothing is lost
if a poll is late. Ubuntu's packaged Python libgpiod uses the version 1 API and the `gpiod`
package on PyPI uses version 2; both are supported here and nothing else imports gpiod.

Open the line BEFORE the panel starts: afterwards the process may no longer be root and
/dev/gpiochip0 may be unreadable. If the line cannot be opened the constructor raises
MotionUnavailable, and the app carries on as if someone is always there.
"""

from __future__ import annotations

import logging
import threading
from types import ModuleType

from .null import NullMotion

log = logging.getLogger("pixelwalk.motion")

FAILURES_BEFORE_UNAVAILABLE = 3


class MotionUnavailable(Exception):
    pass


UnavailableMotion = NullMotion  # the name this module has always exported


class GpioMotionInput:
    def __init__(
        self, chip: str = "gpiochip0", line: int = 16, poll_hz: float = 5.0, gpiod_module: ModuleType | None = None
    ) -> None:
        try:
            gpiod = gpiod_module or __import__("gpiod")
        except ImportError as e:
            raise MotionUnavailable(f"libgpiod is not installed for this Python ({e})") from None
        self._line = line
        self._period = 1.0 / max(0.1, poll_hz)
        self._lock_free_level: bool | None = None
        self._failures = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        try:
            if hasattr(gpiod, "request_lines"):  # libgpiod 2.x
                self._read, self._release = self._open_v2(gpiod, chip, line)
            else:  # libgpiod 1.x
                self._read, self._release = self._open_v1(gpiod, chip, line)
            self._lock_free_level = self._read()
        except MotionUnavailable:
            raise
        except Exception as e:  # noqa: BLE001 (permissions, no such chip, line busy ...)
            raise MotionUnavailable(f"cannot open {chip} line {line}: {type(e).__name__}: {e}") from None

    @staticmethod
    def _open_v2(gpiod, chip, line):
        path = chip if chip.startswith("/") else f"/dev/{chip}"
        req = gpiod.request_lines(
            path,
            consumer="pixelwalk",
            config={line: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT)},
        )
        return (lambda: req.get_value(line) == gpiod.line.Value.ACTIVE), req.release

    @staticmethod
    def _open_v1(gpiod, chip, line):
        c = gpiod.Chip(chip)
        ln = c.get_line(line)
        ln.request(consumer="pixelwalk", type=gpiod.LINE_REQ_DIR_IN)

        def release():
            ln.release()
            c.close()

        return (lambda: bool(ln.get_value())), release

    # --- public ---------------------------------------------------------------------------

    def motion(self) -> bool | None:
        """The latest level, or None if the line has failed repeatedly."""
        return self._lock_free_level

    def poll_once(self) -> None:
        try:
            self._lock_free_level = self._read()
            self._failures = 0
        except Exception as e:  # noqa: BLE001
            self._failures += 1
            if self._failures == FAILURES_BEFORE_UNAVAILABLE:
                log.warning("motion input failing (%s); treating the room as occupied", e)
                self._lock_free_level = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="motion", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def close(self) -> None:
        self.stop()
        try:
            self._release()
        except Exception as e:  # noqa: BLE001
            log.debug("releasing the motion line failed: %s", e)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self._period)
