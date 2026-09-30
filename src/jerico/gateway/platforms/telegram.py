import asyncio
from collections.abc import Callable
from pathlib import Path

from jerico.agent.types import SurfaceType
from jerico.gateway.runner import InboundTurnResponse, OmniGateway
from jerico.voice.stt import STT


async def handle_telegram(
    gateway: OmniGateway,
    user_id: str,
    chat_id: str,
    authorization: str,
    *,
    text: str = "",
    voice_path: Path | None = None,
    transcribe: Callable[[Path], str] | None = None,
) -> InboundTurnResponse:
    if user_id not in gateway.settings.telegram_ids:
        raise PermissionError("telegram user no autorizado")
    if voice_path is not None:
        transcript = (
            await asyncio.to_thread(transcribe, voice_path)
            if transcribe is not None
            else await asyncio.to_thread(STT(gateway.settings.stt_model).transcribe, voice_path)
        )
        if isinstance(transcript, dict):
            if transcript.get("ok") is not True:
                raise RuntimeError(str(transcript.get("error", "STT_FAILED")))
            text = str(transcript.get("text", ""))
        else:
            text = transcript
        if not text.strip():
            raise ValueError("la nota de voz no produjo transcripción")
    return await gateway.handle_inbound_turn(
        f"telegram:{chat_id}:{user_id}", text, SurfaceType.TELEGRAM, authorization
    )
