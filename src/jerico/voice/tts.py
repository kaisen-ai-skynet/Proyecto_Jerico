from pathlib import Path

from jerico.config import get_settings


class TTS:
    """TTS clonada (v0 CPU: Fish S1-mini; v1: Fish S2 / XTTS v2). Stub v0 sin modelo."""

    def __init__(self, engine: str | None = None) -> None:
        settings = get_settings()
        self.engine = engine or settings.tts_engine

    def synthesize(self, text: str, out_path: str | Path | None = None) -> dict[str, object]:
        out = Path(out_path or Path(get_settings().voices_dir) / "out" / "tts.wav")
        return {
            "ok": False,
            "engine": self.engine,
            "text": text,
            "out_path": str(out),
            "error": "TTS_NOT_IMPLEMENTED_V0",
            "note": "v0 stub: síntesis llega en Fase 3; voces fuera del repo con consentimiento.",
        }
