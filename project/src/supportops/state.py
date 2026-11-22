"""Shared state behind interfaces: conversations, trace ownership, rate limiting.

In-memory implementations = single process / tests.  Redis implementations = multi-replica production
(Azure Cache for Redis / Azure Managed Redis; connect with rediss://... TLS URL, key from Key Vault).
Both implement the same methods, so the API does not care which one it gets.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict


# ----------------------------------------------------------------------------- in-memory
class ConversationStore:
    """In-memory LRU. Fine for 1 replica / tests. NOT shared across replicas and lost on restart."""

    def __init__(self, max_conversations: int = 10_000, max_turns: int = 20):
        self._data: OrderedDict[str, dict] = OrderedDict()
        self._traces: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()
        self.max_conversations, self.max_turns = max_conversations, max_turns

    def get_history(self, conv_id: str, owner: str) -> list[dict]:
        with self._lock:
            conv = self._data.get(conv_id)
            if conv is None:
                return []
            if conv["owner"] != owner:                    # same response as "unknown": don't leak existence
                raise KeyError(conv_id)
            return list(conv["turns"])

    def append(self, conv_id: str, owner: str, user_text: str, answer: str) -> None:
        with self._lock:
            conv = self._data.setdefault(conv_id, {"owner": owner, "turns": []})
            conv["turns"] += [{"role": "user", "content": user_text}, {"role": "assistant", "content": answer}]
            conv["turns"] = conv["turns"][-2 * self.max_turns:]
            self._data.move_to_end(conv_id)
            while len(self._data) > self.max_conversations:
                self._data.popitem(last=False)

    def register_trace(self, trace_id: str, owner: str) -> None:
        with self._lock:
            self._traces[trace_id] = owner
            while len(self._traces) > self.max_conversations * 5:
                self._traces.popitem(last=False)

    def trace_owner(self, trace_id: str) -> str | None:
        with self._lock:
            return self._traces.get(trace_id)


class TokenBucket:
    def __init__(self, rate_per_sec: float, burst: int):
        self.rate, self.burst = rate_per_sec, burst
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens < 1:
                self._state[key] = (tokens, now)
                return False
            self._state[key] = (tokens - 1, now)
            return True


# ----------------------------------------------------------------------------- redis
class RedisConversationStore:
    """Conversations as JSON with a TTL (retention!). Last-writer-wins on concurrent appends to the SAME
    conversation (acceptable for a chat UI that sends one message at a time); use a Lua script/Postgres
    transaction if you need strict ordering."""

    def __init__(self, redis, max_turns: int = 20, ttl_seconds: int | None = None):
        self.r = redis
        self.max_turns = max_turns
        self.ttl = ttl_seconds or int(os.getenv("CONVERSATION_TTL_SECONDS", "86400"))

    def get_history(self, conv_id: str, owner: str) -> list[dict]:
        raw = self.r.get(f"conv:{conv_id}")
        if raw is None:
            return []
        conv = json.loads(raw)
        if conv["owner"] != owner:
            raise KeyError(conv_id)
        return conv["turns"]

    def append(self, conv_id: str, owner: str, user_text: str, answer: str) -> None:
        raw = self.r.get(f"conv:{conv_id}")
        conv = json.loads(raw) if raw else {"owner": owner, "turns": []}
        if conv["owner"] != owner:
            raise KeyError(conv_id)
        conv["turns"] += [{"role": "user", "content": user_text}, {"role": "assistant", "content": answer}]
        conv["turns"] = conv["turns"][-2 * self.max_turns:]
        self.r.set(f"conv:{conv_id}", json.dumps(conv), ex=self.ttl)

    def register_trace(self, trace_id: str, owner: str) -> None:
        self.r.set(f"trace:{trace_id}", owner, ex=7 * 86400)

    def trace_owner(self, trace_id: str) -> str | None:
        return self.r.get(f"trace:{trace_id}")


class RedisRateLimiter:
    """Fixed-window counter shared by all replicas: `burst` requests per (burst/rate) seconds per key.
    Simple and atomic (INCR); slightly bursty at window edges. Use a Lua token bucket for stricter smoothing."""

    def __init__(self, redis, rate_per_sec: float, burst: int):
        self.r, self.limit = redis, burst
        self.window = max(1, int(burst / rate_per_sec)) if rate_per_sec > 0 else 10**9

    def allow(self, key: str) -> bool:
        bucket = f"rl:{key}:{int(time.time() // self.window)}"
        n = self.r.incr(bucket)
        if n == 1:
            self.r.expire(bucket, self.window + 1)
        return n <= self.limit


def build_state(rate_per_sec: float, burst: int):
    """REDIS_URL set -> shared Redis state. Otherwise in-memory (and warn: do not run >1 replica)."""
    url = os.getenv("REDIS_URL")
    if url:
        import redis
        r = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
        return RedisConversationStore(r), RedisRateLimiter(r, rate_per_sec, burst)
    return ConversationStore(), TokenBucket(rate_per_sec, burst)
