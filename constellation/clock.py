"""The shared game clock: real time scaled by a warp factor, owned by the host."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Clock:
    """Game time in seconds. Warp changes are continuous: game time never jumps."""

    warp: float = 1.0
    paused: bool = False
    _game_at_mark: float = 0.0
    _real_at_mark: float = field(default_factory=time.monotonic)

    def now(self, real: float | None = None) -> float:
        real = time.monotonic() if real is None else real
        if self.paused:
            return self._game_at_mark
        return self._game_at_mark + (real - self._real_at_mark) * self.warp

    def _mark(self, real: float | None = None) -> float:
        real = time.monotonic() if real is None else real
        self._game_at_mark = self.now(real)
        self._real_at_mark = real
        return real

    def set_warp(self, warp: float, real: float | None = None) -> None:
        if warp <= 0:
            raise ValueError("warp must be positive; use pause()")
        self._mark(real)
        self.warp = warp

    def pause(self, real: float | None = None) -> None:
        self._mark(real)
        self.paused = True

    def resume(self, real: float | None = None) -> None:
        real = time.monotonic() if real is None else real
        self._real_at_mark = real
        self.paused = False

    def set_time(self, game_t: float, real: float | None = None) -> None:
        self._game_at_mark = game_t
        self._real_at_mark = time.monotonic() if real is None else real
