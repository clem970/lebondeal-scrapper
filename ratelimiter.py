import asyncio
import time
from collections import deque

from config import SITE_LIMITS, GLOBAL_KEY_LIMIT


class SlidingWindowLimiter:
    """Limiteur simple à fenêtre glissante: bloque jusqu'à ce qu'un slot soit libre."""

    def __init__(self, max_requests, per_seconds):
        self.max_requests = max_requests
        self.per_seconds = per_seconds
        self._timestamps = deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        if self.max_requests is None:
            return
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] > self.per_seconds:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_requests:
                    self._timestamps.append(now)
                    return
                wait = self.per_seconds - (now - self._timestamps[0]) + 0.05
                await asyncio.sleep(max(wait, 0.05))


class RateLimiterManager:
    """Un limiteur par site + un limiteur global partagé (30 req/min par clé)."""

    def __init__(self):
        self.global_limiter = SlidingWindowLimiter(**GLOBAL_KEY_LIMIT)
        self.site_limiters = {
            site: SlidingWindowLimiter(cfg["max_requests"], cfg["per_seconds"])
            for site, cfg in SITE_LIMITS.items()
        }

    async def acquire(self, site):
        # Le plafond global protège le compte entier, on l'acquiert en dernier pour limiter les faux blocages
        await self.site_limiters[site].acquire()
        await self.global_limiter.acquire()


rate_limiter = RateLimiterManager()
