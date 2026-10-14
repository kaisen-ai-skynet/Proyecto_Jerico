import secrets
import threading
import time
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from jerico.agent.conversation_loop import AgentTurnLoop
from jerico.agent.prompt_builder import PromptBuilder
from jerico.agent.types import SurfaceType
from jerico.config import Settings, get_settings, token_configured
from jerico.gateway.platforms.rest import handle_rest
from jerico.gateway.runner import OmniGateway
from jerico.llm_client import AsyncLLMClient, LLMError
from jerico.memory import memory
from jerico.redis_backends import (
    LocalAsyncMemoryManager,
    LocalAsyncRateLimiter,
    RedisMemoryManager,
    RedisRateLimiter,
    redis_client,
)
from jerico.router import TokenRouter
from jerico.state import StateEngine
from jerico.web import web_router

app = FastAPI(title="Jerico AI-OS", version="0.2.0")
app.include_router(web_router)

# Tope de costo/memoria: cada prompt viaja al LLM y queda en el historial de la sesión.
MAX_PROMPT_CHARS = 20_000
MAX_SESSION_ID_CHARS = 128


class AskRequest(BaseModel):
    prompt: str = Field(max_length=MAX_PROMPT_CHARS)
    session_id: str = Field(default="default", min_length=1, max_length=MAX_SESSION_ID_CHARS)


class AskResponse(BaseModel):
    level: int
    model: str
    answer: str


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        if limit <= 0:
            return True
        with self._lock:
            now = time.monotonic()
            hits = [stamp for stamp in self._hits.get(key, []) if now - stamp < window]
            if len(hits) >= limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


@lru_cache(maxsize=1)
def get_router() -> TokenRouter:
    return TokenRouter(get_settings())


@lru_cache(maxsize=1)
def get_llm() -> AsyncLLMClient:
    # Una instancia: reutiliza el pool HTTP en vez de abrir un cliente por request.
    return AsyncLLMClient(get_settings())


def get_memory_backend() -> LocalAsyncMemoryManager | RedisMemoryManager:
    settings = get_settings()
    if not settings.redis_url:
        return LocalAsyncMemoryManager(memory)
    return RedisMemoryManager(
        redis_client(settings.redis_url),
        memory,
        ttl_seconds=settings.memory_ttl_hours * 3600,
        max_sessions=settings.memory_max_sessions,
    )


def get_rate_limiter() -> LocalAsyncRateLimiter | RedisRateLimiter:
    settings = get_settings()
    if not settings.redis_url:
        return LocalAsyncRateLimiter(limiter)
    return RedisRateLimiter(redis_client(settings.redis_url), limiter)


@lru_cache(maxsize=1)
def get_agent_loop() -> AgentTurnLoop:
    settings = get_settings()
    state = StateEngine(settings.state_db_path)
    return AgentTurnLoop(
        state,
        get_llm(),
        router=TokenRouter(settings),
        prompt_builder=PromptBuilder(""),
    )


def require_token(authorization: str, settings: Settings) -> None:
    if not token_configured(settings.api_token):
        raise HTTPException(status_code=401, detail="token_not_configured")
    expected = f"Bearer {settings.api_token}"
    # En bytes: compare_digest con str no-ASCII lanza TypeError (500 en vez de 401).
    if not secrets.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="unauthorized")


def get_authenticated_agent_loop(
    authorization: str = Header(default=""),
) -> AgentTurnLoop:
    require_token(authorization, get_settings())
    return get_agent_loop()


@app.get("/health")
async def health() -> dict[str, str]:
    # async: no compite por el threadpool con /ask (hasta ~90 s por request al LLM).
    return {"status": "ok", "service": "jerico", "version": "0.2.0"}


@app.post("/api/v1/ask", response_model=AskResponse)
async def ask(
    req: AskRequest,
    agent: Annotated[AgentTurnLoop, Depends(get_authenticated_agent_loop)],
    rate_limiter: Annotated[LocalAsyncRateLimiter | RedisRateLimiter, Depends(get_rate_limiter)],
    authorization: str = Header(default=""),
) -> AskResponse:
    settings = get_settings()
    if not await rate_limiter.allow(authorization, settings.rate_limit_per_min):
        raise HTTPException(status_code=429, detail="rate_limit")
    try:
        response = await handle_rest(
            OmniGateway(agent, settings), req.session_id, req.prompt, authorization
        )
        result = response.result
    except TimeoutError as exc:
        raise HTTPException(status_code=409, detail="session_busy") from exc
    except LLMError as exc:
        logger.warning(f"llm_unavailable: {exc}")
        raise HTTPException(status_code=502, detail="llm_unavailable") from exc
    return AskResponse(level=result.level, model=result.model, answer=result.answer)


@app.post("/api/v1/siri", response_model=AskResponse)
async def ask_siri(
    req: AskRequest,
    agent: Annotated[AgentTurnLoop, Depends(get_authenticated_agent_loop)],
    rate_limiter: Annotated[LocalAsyncRateLimiter | RedisRateLimiter, Depends(get_rate_limiter)],
    authorization: str = Header(default=""),
) -> AskResponse:
    settings = get_settings()
    if not await rate_limiter.allow(authorization, settings.rate_limit_per_min):
        raise HTTPException(status_code=429, detail="rate_limit")
    try:
        response = await OmniGateway(agent, settings).handle_inbound_turn(
            req.session_id, req.prompt, SurfaceType.SIRI, authorization
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=409, detail="session_busy") from exc
    except LLMError as exc:
        logger.warning(f"llm_unavailable: {exc}")
        raise HTTPException(status_code=502, detail="llm_unavailable") from exc
    answer = " ".join(response.answer.split())
    if len(answer) > 280:
        answer = answer[:279] + "…"
    return AskResponse(level=response.result.level, model=response.result.model, answer=answer)
