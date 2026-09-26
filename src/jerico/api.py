import secrets
import time

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from jerico.config import Settings, get_settings, token_configured
from jerico.llm_client import LLMClient
from jerico.memory import memory
from jerico.router import TokenRouter

app = FastAPI(title="Jerico AI-OS", version="0.2.0")


class AskRequest(BaseModel):
    prompt: str
    session_id: str = "default"


class AskResponse(BaseModel):
    level: int
    model: str
    answer: str


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        hits = [stamp for stamp in self._hits.get(key, []) if now - stamp < window]
        if len(hits) >= limit:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()


def get_router() -> TokenRouter:
    return TokenRouter(get_settings())


def get_llm() -> LLMClient:
    return LLMClient(get_settings())


def require_token(authorization: str, settings: Settings) -> None:
    if not token_configured(settings.api_token):
        raise HTTPException(status_code=401, detail="token_not_configured")
    expected = f"Bearer {settings.api_token}"
    if not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "jerico", "version": "0.2.0"}


@app.post("/api/v1/ask", response_model=AskResponse)
def ask(req: AskRequest, authorization: str = Header(default="")) -> AskResponse:
    settings = get_settings()
    require_token(authorization, settings)
    if not limiter.allow(authorization, settings.rate_limit_per_min):
        raise HTTPException(status_code=429, detail="rate_limit")
    decision = get_router().route(req.prompt)
    if decision.answer is not None:
        answer = decision.answer
    else:
        answer = get_llm().complete(
            req.prompt,
            level=decision.level,
            history=memory.context(req.session_id),
        )
    memory.append(req.session_id, "user", req.prompt)
    memory.append(req.session_id, "assistant", answer)
    return AskResponse(level=decision.level, model=decision.model, answer=answer)
