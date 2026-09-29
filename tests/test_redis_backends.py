import asyncio

import fakeredis.aioredis
import pytest
from redis.exceptions import ConnectionError

from jerico.api import RateLimiter
from jerico.memory import MemoryManager
from jerico.redis_backends import (
    REDIS_TIMEOUT_SECONDS,
    RedisMemoryManager,
    RedisRateLimiter,
    redis_client,
)


@pytest.mark.asyncio
async def test_cliente_redis_se_crea_sin_conexion_y_con_timeouts():
    client = redis_client("redis://127.0.0.1:1/0")
    try:
        kwargs = client.connection_pool.connection_kwargs
        assert kwargs["socket_connect_timeout"] == REDIS_TIMEOUT_SECONDS
        assert kwargs["socket_timeout"] == REDIS_TIMEOUT_SECONDS
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_redis_memory_guarda_contexto_recorta_y_limita_sesiones():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    manager = RedisMemoryManager(
        client, MemoryManager(), max_messages=4, ttl_seconds=60, max_sessions=2
    )
    try:
        await manager.record_turn("a", "q1", "a1")
        await manager.record_turn("a", "q2", "a2")
        assert await manager.context("a") == [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        await manager.record_turn("b", "qb", "ab")
        await manager.record_turn("c", "qc", "ac")
        assert await manager.context("a") == []
        assert await manager.context("c") == [
            {"role": "user", "content": "qc"},
            {"role": "assistant", "content": "ac"},
        ]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_redis_memory_transacciones_no_intercalan_turnos():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    manager = RedisMemoryManager(client, MemoryManager(), max_messages=500)
    try:
        await asyncio.gather(*(manager.record_turn("shared", f"q{i}", f"a{i}") for i in range(100)))
        messages = await manager.context("shared")
        assert len(messages) == 200
        for user, assistant in zip(messages[::2], messages[1::2], strict=True):
            assert user["role"] == "user"
            assert assistant["role"] == "assistant"
            assert user["content"][1:] == assistant["content"][1:]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_redis_rate_limit_compartido_y_clave_no_revela_token():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    limiter = RedisRateLimiter(client, RateLimiter())
    try:
        assert await limiter.allow("Bearer private-token", 2)
        assert await limiter.allow("Bearer private-token", 2)
        assert not await limiter.allow("Bearer private-token", 2)
        keys = await client.keys("jerico:rate:*")
        assert len(keys) == 1
        assert "private-token" not in keys[0]
    finally:
        await client.aclose()


class UnavailableRedis:
    def pipeline(self, **_kwargs):
        raise ConnectionError("offline")

    async def exists(self, *_args):
        raise ConnectionError("offline")

    async def zrem(self, *_args):
        raise ConnectionError("offline")

    async def set(self, *_args, **_kwargs):
        raise ConnectionError("offline")


@pytest.mark.asyncio
async def test_memoria_y_rate_limit_caen_a_ram_si_redis_falla():
    local_memory = MemoryManager()
    memory_backend = RedisMemoryManager(UnavailableRedis(), local_memory)  # type: ignore[arg-type]
    await memory_backend.record_turn("session", "pregunta", "respuesta")
    assert await memory_backend.context("session") == [
        {"role": "user", "content": "pregunta"},
        {"role": "assistant", "content": "respuesta"},
    ]

    local_limiter = RateLimiter()
    rate_backend = RedisRateLimiter(UnavailableRedis(), local_limiter)  # type: ignore[arg-type]
    assert await rate_backend.allow("token", 1)
    assert not await rate_backend.allow("token", 1)
