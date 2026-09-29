import hashlib
import json
import math
import time
from functools import lru_cache
from typing import Any

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from jerico.memory import MemoryManager

REDIS_TIMEOUT_SECONDS = 0.5
_REDIS_FAILURES = (RedisError, TimeoutError, OSError)
_MEMORY_FAILURES = (*_REDIS_FAILURES, json.JSONDecodeError, TypeError)


@lru_cache(maxsize=8)
def redis_client(url: str) -> Redis:
    """Crea un cliente sin conectar; cada operación queda limitada por timeout."""
    return Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
        retry_on_timeout=False,
    )


class LocalAsyncMemoryManager:
    """Adaptador async del backend RAM para el pipeline FastAPI."""

    def __init__(self, manager: MemoryManager) -> None:
        self.manager = manager

    async def context(self, session_id: str) -> list[dict[str, str]]:
        return self.manager.context(session_id)

    async def record_turn(self, session_id: str, prompt: str, answer: str) -> None:
        self.manager.record_turn(session_id, prompt, answer)


class RedisMemoryManager:
    """Memoria de sesión en Redis con fallback RAM acotado por timeout."""

    def __init__(
        self,
        client: Redis,
        fallback: MemoryManager,
        *,
        max_messages: int = 20,
        ttl_seconds: int = 24 * 3600,
        max_sessions: int = 100,
        prefix: str = "jerico:memory",
    ) -> None:
        self.client = client
        self.fallback = fallback
        self.max_messages = max_messages
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max(1, max_sessions)
        self.prefix = prefix
        self._index = f"{prefix}:sessions"

    def _key(self, session_id: str) -> str:
        return f"{self.prefix}:{session_id}"

    async def context(self, session_id: str) -> list[dict[str, str]]:
        key = self._key(session_id)
        try:
            if not await self.client.exists(key):
                await self.client.zrem(self._index, key)
                return []
            pipe = self.client.pipeline(transaction=True)
            pipe.lrange(key, 0, -1)
            if self.ttl_seconds > 0:
                pipe.expire(key, self.ttl_seconds)
            pipe.zadd(self._index, {key: time.time()})
            results = await pipe.execute()
            return [json.loads(item) for item in results[0]]
        except _MEMORY_FAILURES as exc:
            logger.warning(f"redis_memory_fallback context: {type(exc).__name__}")
            return self.fallback.context(session_id)

    async def record_turn(self, session_id: str, prompt: str, answer: str) -> None:
        key = self._key(session_id)
        user_message = json.dumps({"role": "user", "content": prompt}, ensure_ascii=False)
        assistant_message = json.dumps({"role": "assistant", "content": answer}, ensure_ascii=False)
        try:
            pipe = self.client.pipeline(transaction=True)
            pipe.rpush(key, user_message, assistant_message)
            pipe.ltrim(key, -self.max_messages, -1)
            if self.ttl_seconds > 0:
                pipe.expire(key, self.ttl_seconds)
            pipe.zadd(self._index, {key: time.time()})
            await pipe.execute()
            await self._enforce_session_limit()
        except _REDIS_FAILURES as exc:
            logger.warning(f"redis_memory_fallback record_turn: {type(exc).__name__}")
            self.fallback.record_turn(session_id, prompt, answer)

    async def _enforce_session_limit(self) -> None:
        members = await self.client.zrange(self._index, 0, -1, withscores=True)
        stale: list[str] = []
        active: list[str] = []
        for member, _score in members:
            if await self.client.exists(member):
                active.append(member)
            else:
                stale.append(member)
        if stale:
            await self.client.zrem(self._index, *stale)
        excess = len(active) - self.max_sessions
        if excess <= 0:
            return
        evicted = await self.client.zrange(self._index, 0, excess - 1)
        if evicted:
            pipe = self.client.pipeline(transaction=True)
            pipe.delete(*evicted)
            pipe.zrem(self._index, *evicted)
            await pipe.execute()


class LocalAsyncRateLimiter:
    """Adaptador async para el rate limiter RAM de un solo proceso."""

    def __init__(self, limiter: Any) -> None:
        self.limiter = limiter

    async def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        return self.limiter.allow(key, limit, window)


class RedisRateLimiter:
    """Contador de ventana fija compartido entre workers, con fallback local."""

    def __init__(self, client: Redis, fallback: Any, *, prefix: str = "jerico:rate") -> None:
        self.client = client
        self.fallback = fallback
        self.prefix = prefix

    async def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        if limit <= 0:
            return True
        digest = hashlib.sha256(key.encode()).hexdigest()
        redis_key = f"{self.prefix}:{digest}"
        ttl = max(1, math.ceil(window))
        try:
            created = await self.client.set(redis_key, 1, ex=ttl, nx=True)
            if created:
                return True
            count = await self.client.incr(redis_key)
            if await self.client.ttl(redis_key) < 0:
                await self.client.expire(redis_key, ttl)
            return count <= limit
        except _REDIS_FAILURES as exc:
            logger.warning(f"redis_rate_limit_fallback: {type(exc).__name__}")
            return self.fallback.allow(key, limit, window)
