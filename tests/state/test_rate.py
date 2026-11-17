import pytest
from fakeredis import FakeAsyncRedis

from risk_service.state.keys import rate_key
from risk_service.state.rate import RateLimiter


class FakeClock:
    def __init__(self, now_ms: int = 1_000_000) -> None:
        self.now_ms = now_ms

    def __call__(self) -> int:
        return self.now_ms


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def limiter(redis: FakeAsyncRedis, clock: FakeClock) -> RateLimiter:
    return RateLimiter(redis, window_ms=1000, clock=clock)


async def test_counts_hits_in_window(limiter: RateLimiter) -> None:
    assert [await limiter.hit("A") for _ in range(3)] == [1, 2, 3]


async def test_window_slides(limiter: RateLimiter, clock: FakeClock) -> None:
    start = clock.now_ms
    await limiter.hit("A")  # hits: {0}
    clock.now_ms = start + 600
    assert await limiter.hit("A") == 2  # {0, 600}
    clock.now_ms = start + 1000
    assert await limiter.hit("A") == 2  # 0 is exactly one window old and drops: {600, 1000}
    clock.now_ms = start + 1600
    assert await limiter.hit("A") == 2  # {1000, 1600}
    clock.now_ms = start + 2600
    assert await limiter.hit("A") == 1  # {2600}


async def test_accounts_are_independent(limiter: RateLimiter) -> None:
    await limiter.hit("A")
    await limiter.hit("A")
    assert await limiter.hit("B") == 1


async def test_key_expires(limiter: RateLimiter, redis: FakeAsyncRedis) -> None:
    await limiter.hit("A")
    ttl = await redis.pttl(rate_key("A"))
    assert 0 < ttl <= 1000


def test_window_must_be_positive(redis: FakeAsyncRedis) -> None:
    with pytest.raises(ValueError, match="positive"):
        RateLimiter(redis, window_ms=0)
