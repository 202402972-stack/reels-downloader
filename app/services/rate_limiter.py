from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque


class RateLimitExceeded(Exception):
    pass


class RateLimiter:
    def __init__(self, min_interval: int, max_per_minute: int) -> None:
        self.min_interval = min_interval
        self.max_per_minute = max_per_minute
        self.last_request: dict[int, float] = {}
        self.requests: dict[int, deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()

    async def check(self, user_id: int) -> None:
        now = time.monotonic()
        async with self.lock:
            recent = self.requests[user_id]
            while recent and now - recent[0] > 60:
                recent.popleft()
            if recent and now - recent[-1] < self.min_interval:
                raise RateLimitExceeded
            if len(recent) >= self.max_per_minute:
                raise RateLimitExceeded
            recent.append(now)
            self.last_request[user_id] = now