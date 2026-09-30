from jerico.agent.types import SurfaceType
from jerico.gateway.runner import OmniGateway


async def handle_siri(
    gateway: OmniGateway, session_id: str, prompt: str, authorization: str, *, max_chars: int = 280
) -> str:
    if max_chars < 1:
        raise ValueError("max_chars debe ser positivo")
    response = await gateway.handle_inbound_turn(
        session_id, prompt, SurfaceType.SIRI, authorization
    )
    answer = " ".join(response.answer.split())
    return answer if len(answer) <= max_chars else answer[: max_chars - 1] + "…"
