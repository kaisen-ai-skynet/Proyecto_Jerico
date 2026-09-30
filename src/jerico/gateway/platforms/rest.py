from jerico.agent.types import SurfaceType
from jerico.gateway.runner import InboundTurnResponse, OmniGateway


async def handle_rest(
    gateway: OmniGateway, session_id: str, prompt: str, authorization: str
) -> InboundTurnResponse:
    return await gateway.handle_inbound_turn(session_id, prompt, SurfaceType.REST, authorization)
