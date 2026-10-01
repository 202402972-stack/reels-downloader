import pytest

from app.services.rate_limiter import RateLimitExceeded, RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_rejects_fast_repeats() -> None:
    limiter = RateLimiter(min_interval=10, max_per_minute=3)
    await limiter.check(1)
    with pytest.raises(RateLimitExceeded):
        await limiter.check(1)


@pytest.mark.asyncio
async def test_rate_limiter_allows_different_users() -> None:
    limiter = RateLimiter(min_interval=10, max_per_minute=3)
    await limiter.check(1)
    await limiter.check(2)