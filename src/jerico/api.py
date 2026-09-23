from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from jerico.config import get_settings
from jerico.llm_client import LLMClient
from jerico.memory import memory
from jerico.router import TokenRouter

app = FastAPI(title="Jerico AI-OS", version="0.1.0")
router = TokenRouter()
llm = LLMClient()


class AskRequest(BaseModel):
    prompt: str
    session_id: str = "default"


class AskResponse(BaseModel):
    level: int
    model: str
    answer: str


def require_token(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {get_settings().api_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "jerico", "version": "0.1.0"}


@app.post("/api/v1/ask", response_model=AskResponse, dependencies=[Depends(require_token)])
async def ask(req: AskRequest) -> AskResponse:
    decision = router.route(req.prompt)
    if decision.answer is not None:
        answer = decision.answer
    else:
        history = memory.context(req.session_id)
        history.append({"role": "user", "content": req.prompt})
        answer = llm.complete(req.prompt, level=decision.level)
    memory.append(req.session_id, "user", req.prompt)
    memory.append(req.session_id, "assistant", answer)
    return AskResponse(level=decision.level, model=decision.model, answer=answer)
