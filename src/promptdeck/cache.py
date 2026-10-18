"""Per-process bounded LRU with TTL, stale-while-error and single-flight loading."""

from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")
Key = tuple[str, str, str]


@dataclass(slots=True)
class Entry(Generic[T]):
    value: T
    expires_at: float
    loaded_at: float


class PromptCache(Generic[T]):
    """Thread-safe LRU. ``now`` is monotonic time; a hit is a dict lookup and one comparison."""

    __slots__ = ("_data", "_lock", "_inflight", "_ainflight", "max_entries", "hits", "misses")

    def __init__(self, max_entries: int) -> None:
        self._data: OrderedDict[Key, Entry[T]] = OrderedDict()
        self._lock = threading.Lock()
        self._inflight: dict[Key, threading.Lock] = {}
        self._ainflight: dict[Key, asyncio.Future[T]] = {}
        self.max_entries = max_entries
        self.hits = 0
        self.misses = 0

    # -- reads -----------------------------------------------------------------------------------

    def fresh(self, key: Key) -> T | None:
        """Return the value if present and not expired (moves it to most-recent)."""
        e = self._data.get(key)
        if e is None or e.expires_at <= time.monotonic():
            self.misses += 1
            return None
        self.hits += 1
        with self._lock:
            self._data.move_to_end(key)
        return e.value

    def stale(self, key: Key, max_stale: float) -> T | None:
        """Return an expired value if it was loaded less than ``max_stale`` seconds ago."""
        e = self._data.get(key)
        if e is None or time.monotonic() - e.loaded_at > max_stale:
            return None
        return e.value

    # -- writes ----------------------------------------------------------------------------------

    def put(self, key: Key, value: T, ttl: float) -> None:
        now = time.monotonic()
        with self._lock:
            self._data[key] = Entry(value, now + ttl, now)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def retain(self, key: Key, value: T, ttl: float) -> None:
        """Re-arm an expired entry for ``ttl`` seconds without resetting its ``loaded_at``."""
        with self._lock:
            e = self._data.get(key)
            loaded = e.loaded_at if e is not None else time.monotonic()
            self._data[key] = Entry(value, time.monotonic() + ttl, loaded)

    def invalidate(self, name: str | None = None) -> int:
        """Drop entries for ``name`` (all labels/locales), or everything when ``name`` is None."""
        with self._lock:
            if name is None:
                n = len(self._data)
                self._data.clear()
                return n
            keys = [k for k in self._data if k[0] == name]
            for k in keys:
                del self._data[k]
            return len(keys)

    def __len__(self) -> int:
        return len(self._data)

    def stats(self) -> dict[str, float | int]:
        total = self.hits + self.misses
        return {
            "size": len(self._data),
            "max_entries": self.max_entries,
            "hits": self.hits,
            "misses": self.misses,
            "hit_ratio": round(self.hits / total, 4) if total else 0.0,
        }

    # -- single-flight ---------------------------------------------------------------------------

    def load(self, key: Key, loader: Callable[[], T], ttl: float) -> T:
        """Load ``key`` once even when many threads miss at the same time."""
        with self._lock:
            lock = self._inflight.get(key)
            leader = lock is None
            if leader:
                lock = self._inflight[key] = threading.Lock()
                lock.acquire()
        assert lock is not None
        if not leader:
            with lock:  # wait for the leader
                value = self.fresh(key)
                if value is not None:
                    return value
            return loader()  # leader failed or ttl=0: load ourselves
        try:
            value = loader()
            if ttl > 0:
                self.put(key, value, ttl)
            return value
        finally:
            with self._lock:
                self._inflight.pop(key, None)
            lock.release()

    async def aload(self, key: Key, loader: Callable[[], Awaitable[T]], ttl: float) -> T:
        """Async single-flight: concurrent tasks await one future."""
        fut = self._ainflight.get(key)
        if fut is not None:
            return await asyncio.shield(fut)
        fut = asyncio.get_running_loop().create_future()
        self._ainflight[key] = fut
        try:
            value = await loader()
        except BaseException as e:
            fut.set_exception(e)
            fut.exception()  # mark retrieved: waiters get it via shield, nobody else needs the log
            raise
        else:
            if ttl > 0:
                self.put(key, value, ttl)
            fut.set_result(value)
            return value
        finally:
            self._ainflight.pop(key, None)
            if not fut.done():  # cancelled before completion
                fut.cancel()
