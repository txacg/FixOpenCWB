"""Per-credential in-memory cache with request deduplication and error backoff."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any


@dataclass(frozen=True)
class Cached:
    value: Any
    fetched_at: datetime
    expires: float


class DataCache:
    def __init__(self):
        self.entries: dict[tuple, Cached] = {}
        self._pending: dict[tuple, asyncio.Task] = {}
        self._errors: dict[tuple, tuple[Exception, float]] = {}

    async def get(
        self, key: tuple, fetch: Callable[[], Awaitable[Any]], ttl: float
    ) -> Cached:
        if key in self.entries and self.entries[key].expires > monotonic():
            return self.entries[key]
        if key in self._errors and self._errors[key][1] > monotonic():
            raise self._errors[key][0]
        if key not in self._pending:

            async def load():
                try:
                    value = await fetch()
                    cached = Cached(value, datetime.now(UTC), monotonic() + ttl)
                    self.entries[key] = cached
                    self._errors.pop(key, None)
                    return cached
                except Exception as error:
                    # Remember and re-raise; never suppress a failed request.
                    self._errors[key] = (error, monotonic() + 60)
                    raise
                finally:
                    self._pending.pop(key, None)

            self._pending[key] = asyncio.create_task(load())
        return await asyncio.shield(self._pending[key])

    async def close(self):
        tasks = list(self._pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.entries.clear()
        self._errors.clear()
