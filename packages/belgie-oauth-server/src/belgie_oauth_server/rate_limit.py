from __future__ import annotations

import time
from dataclasses import dataclass

from belgie_oauth_server.settings import OAuthServerRateLimitRule  # noqa: TC001


@dataclass(slots=True)
class _RateLimitBucket:
    count: int
    reset_at: float


class OAuthServerRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _RateLimitBucket] = {}

    def check(self, bucket: str, key: str, rule: OAuthServerRateLimitRule | None) -> tuple[bool, int | None]:
        if rule is None:
            return True, None

        now = time.time()
        cache_key = (bucket, key)
        state = self._buckets.get(cache_key)
        if state is None or now >= state.reset_at:
            state = _RateLimitBucket(count=0, reset_at=now + rule.window)
            self._buckets[cache_key] = state

        if state.count >= rule.max:
            retry_after = max(int(state.reset_at - now), 0)
            return False, retry_after

        state.count += 1
        return True, max(int(state.reset_at - now), 0)
