"""Wall-clock time in integer milliseconds, injectable for tests."""

import time
from collections.abc import Callable

Clock = Callable[[], int]


def now_ms() -> int:
    return time.time_ns() // 1_000_000
