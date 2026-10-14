"""Cliente de Jev (TypeSafe AI) para el Nivel 2 en línea (spec 007, VJT-031 a VJT-053).

Implementación única en producción usando exclusivamente la biblioteca estándar de Python.
"""

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jerico.decision.policy import PolicyKind

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT: str = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL: str = "jev-1.13.0"  # Q8: versión fija semver según la Constitución

_CORREO = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_NUMERO_LARGO = re.compile(r"\d{9,}")

Transport = Callable[[dict[str, Any], dict[str, str], float], tuple[int, dict[str, Any] | None]]


def validar_state_privacidad(state: Any) -> None:
    """Rechaza datos personales evidentes antes de salir de la máquina (Ley 1581, VJT-020)."""
    texto = json.dumps(state, ensure_ascii=False)
    if _CORREO.search(texto) or _NUMERO_LARGO.search(texto):
        raise ValueError(
            "El state parece llevar datos personales (correo o número largo); no se envía"
        )


def cargar_llave_typesafe(env_path: Path | str | None = None) -> str | None:
    """Lee TYPESAFE_API_KEY del entorno o del archivo .env sin imprimirla ni registrarla."""
    env_val = os.environ.get("TYPESAFE_API_KEY")
    if env_val is not None and env_val.strip():
        return env_val.strip()

    target = Path(env_path) if env_path is not None else Path(".env")
    if not target.is_file():
        # Intentar en raíz de repositorio si estamos en subcarpeta
        root_target = Path(__file__).resolve().parents[3] / ".env"
        if root_target.is_file():
            target = root_target
        else:
            return None

    try:
        with target.open("r", encoding="utf-8") as f:
            for line in f:
                clean = line.strip()
                if not clean or clean.startswith("#"):
                    continue
                if clean.startswith("TYPESAFE_API_KEY="):
                    val = clean.split("=", 1)[1].strip().strip("'\"").strip()
                    return val if val else None
    except OSError:
        return None
    return None


def _default_urllib_transport(
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_s: float,
    endpoint: str = DEFAULT_ENDPOINT,
) -> tuple[int, dict[str, Any] | None]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            status = int(resp.status)
            raw = resp.read().decode("utf-8")
            body = json.loads(raw) if status == 200 and raw else None
            return status, body
    except urllib.error.HTTPError as e:
        return int(e.code), None
    except (urllib.error.URLError, TimeoutError) as e:
        if isinstance(e, TimeoutError) or "timed out" in str(e).lower():
            raise TimeoutError(f"Jev no respondió en {timeout_s:g} s") from None
        raise RuntimeError(f"error de conexión con Jev: {type(e).__name__}") from None


class JevClient:
    """Cliente para consultar a Jev (TypeSafe systemone) en Nivel 2."""

    def __init__(
        self,
        transport: Transport | None = None,
        api_key: str | None = None,
        endpoint: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout_s: float = 3.0,
        backoff_s: float = 0.3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.endpoint = endpoint or DEFAULT_ENDPOINT
        self.model = model
        self.timeout_s = timeout_s
        self.backoff_s = backoff_s
        self._sleep = sleep
        self._key = api_key if api_key is not None else cargar_llave_typesafe()
        self._transport = transport

    @property
    def enabled(self) -> bool:
        """Indica si el cliente cuenta con llave de autenticación disponible."""
        return bool(self._key)

    def __repr__(self) -> str:
        # Nunca incluye la clave en el __repr__ (VJT-051)
        return (
            f"JevClient(enabled={self.enabled}, endpoint={self.endpoint!r}, model={self.model!r})"
        )

    def __str__(self) -> str:
        return repr(self)

    def _sanitize_error_message(self, msg: str) -> str:
        """Elimina cualquier rastro accidental de la clave secreta de los mensajes de error."""
        if self._key and self._key in msg:
            return msg.replace(self._key, "[REDACTED_API_KEY]")
        return msg

    def _call_transport(
        self, payload: dict[str, Any], headers: dict[str, str], timeout_s: float
    ) -> tuple[int, dict[str, Any] | None]:
        if self._transport is not None:
            return self._transport(payload, headers, timeout_s)
        return _default_urllib_transport(payload, headers, timeout_s, endpoint=self.endpoint)

    def consultar(self, spec: PolicyKind | dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una consulta única a Jev para el tipo especificado (VJT-031, VJT-035).

        Interpreta 'choice' o 'score', reintenta 429 y 529, respeta el tiempo máximo y
        detecta empate de probabilidades (VJT-037).
        """
        # 1. Validación de privacidad del state (VJT-020)
        validar_state_privacidad(state)

        if not self.enabled:
            raise RuntimeError("sin llave TYPESAFE_API_KEY")

        # 2. Extracción de tipo y opciones
        if isinstance(spec, PolicyKind):
            kind = spec.kind
            opciones = spec.opciones
            base = spec.base
            questions = {kind: {"type": "choice", "criteria": {opt: opt for opt in opciones}}}
        else:
            kind = str(spec.get("kind", "decision"))
            opciones = list(spec.get("opciones", []))
            base = str(spec.get("base", opciones[0] if opciones else ""))
            if "questions" in spec:
                questions = spec["questions"]
            else:
                questions = {kind: {"type": "choice", "criteria": {opt: opt for opt in opciones}}}

        payload: dict[str, Any] = {
            "state": state,
            "model": self.model,
            "questions": questions,
        }

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }

        t0 = time.monotonic()
        try:
            status, body = self._call_transport(payload, headers, self.timeout_s)
            # Reintento único ante 429 o 529 (VJT-031)
            if status in (429, 529):
                self._sleep(self.backoff_s)
                status, body = self._call_transport(payload, headers, self.timeout_s)

        except TimeoutError as exc:
            raise TimeoutError(self._sanitize_error_message(str(exc))) from None
        except Exception as exc:
            clean_msg = self._sanitize_error_message(str(exc))
            raise RuntimeError(f"error en consulta a Jev: {clean_msg}") from None

        latencia_ms = round((time.monotonic() - t0) * 1000, 1)

        if status != 200 or body is None:
            raise RuntimeError(f"Jev respondió HTTP {status}")

        return self._parse_response(body, kind, opciones, base, latencia_ms)

    def _parse_response(
        self,
        body: dict[str, Any],
        kind: str,
        opciones: list[str],
        base: str,
        latencia_ms: float,
    ) -> dict[str, Any]:
        """Interpreta la respuesta de Jev (choice / score, empate y metadatos)."""
        answers_raw = body.get("answers")
        if isinstance(answers_raw, list):
            answers = {a.get("id") or a.get("name"): a for a in answers_raw if isinstance(a, dict)}
        elif isinstance(answers_raw, dict):
            answers = answers_raw
        else:
            raise ValueError("respuesta de Jev sin answers válidas")

        ans = answers.get(kind)
        if ans is None and len(answers) == 1:
            ans = next(iter(answers.values()))

        if not isinstance(ans, dict):
            raise ValueError(f"falta respuesta para {kind}")

        # Extraer choice o score
        val: str | None = None
        raw_choice = ans.get("choice")
        if raw_choice is not None and str(raw_choice) in opciones:
            val = str(raw_choice)
        elif raw_choice is not None:
            val = str(raw_choice)

        raw_score = ans.get("score")
        if val is None and raw_score is not None:
            if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
                if opciones:
                    idx = min(max(round(float(raw_score)), 0), len(opciones) - 1)
                    val = opciones[idx]
                else:
                    val = str(raw_score)
            else:
                val = str(raw_score)

        if val is None:
            val = base

        # Extraer probabilidades
        probs_raw = ans.get("probabilities")
        probs: dict[str, float] = {}
        if isinstance(probs_raw, dict):
            probs = {k: float(v) for k, v in probs_raw.items()}

        raw_conf = ans.get("confidence")
        if raw_conf is not None:
            confidence = float(raw_conf)
        elif val in probs:
            confidence = probs[val]
        else:
            confidence = 1.0 if not opciones else (1.0 / len(opciones))

        # Detección de empate (VJT-037)
        empate = False
        if probs and len(probs) >= 2:
            sorted_probs = sorted(probs.values(), reverse=True)
            if abs(sorted_probs[0] - sorted_probs[1]) < 1e-5:
                empate = True

        usage = body.get("usage") or {}
        tokens_in = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
        tokens_out = usage.get("output_tokens", 0) if isinstance(usage, dict) else 0
        model_version = str(body.get("model") or self.model)

        return {
            "option": val,
            "score": raw_score,
            "confidence": confidence,
            "probabilities": probs,
            "empate": empate,
            "model": model_version,
            "model_version": model_version,
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "latencia_ms": latencia_ms,
        }
