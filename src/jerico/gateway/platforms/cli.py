import asyncio
from collections.abc import Callable

from jerico.agent.types import SurfaceType
from jerico.gateway.runner import OmniGateway


async def interactive_cli(
    gateway: OmniGateway,
    session_id: str,
    authorization: str,
    *,
    read: Callable[[], str] = input,
    write: Callable[[str], object] = print,
) -> None:
    while True:
        try:
            prompt = await asyncio.to_thread(read)
        except EOFError:
            return
        if prompt.strip() in {"/exit", "/quit"}:
            return
        response = await gateway.handle_inbound_turn(
            session_id, prompt, SurfaceType.CLI, authorization
        )
        write(response.answer)
