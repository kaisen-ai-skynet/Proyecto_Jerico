from pathlib import Path


class STT:
    """STT faster-whisper (lazy import; opcional voice extra). Half-duplex, no streaming."""

    def __init__(self, model_size: str = "small") -> None:
        self.model_size = model_size

        self._model = None

    def _load(self) -> object:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_size, compute_type="int8")
        return self._model

    def transcribe(self, audio_path: str | Path) -> dict[str, object]:
        path = Path(audio_path)
        if not path.exists():
            return {"ok": False, "error": "FILE_NOT_FOUND", "path": str(path)}
        try:
            model = self._load()
            segments, info = model.transcribe(str(path))
            text = " ".join(seg.text for seg in segments).strip()
            return {"ok": True, "text": text, "language": info.language}
        except ImportError:
            return {
                "ok": False,
                "error": "VOICE_EXTRA_MISSING",
                "hint": "pip install -e '.[voice]'",
            }
