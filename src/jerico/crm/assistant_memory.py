"""Memoria persistente en SQLite WAL para el asistente de Jericó (Spec 005 - Fase A1).

Garantiza:
1. Persistencia estricta en SQLite WAL (sobrevive reinicios del servicio).
2. Aislamiento por usuario y rol (el comercial nunca ve la del CTO ni la de otro comercial).
3. Invariante de prompt de sistema inmutable por SHA-256.
4. Resúmenes de compactación persistidos en la sesión.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jerico.state import StateEngine


class AccessDeniedError(PermissionError):
    """Acceso denegado a una sesión que no pertenece al usuario solicitante."""


@dataclass(frozen=True)
class AssistantSessionRecord:
    session_id: str
    user_id: int
    role: str
    model: str
    system_prompt_hash: str
    created_at: str
    updated_at: str


class AssistantMemory:
    """Capa de memoria persistente para el asistente sobre StateEngine."""

    def __init__(self, db_path: Path | str | StateEngine) -> None:
        if isinstance(db_path, StateEngine):
            self.engine = db_path
            self._owns_engine = False
        else:
            self.engine = StateEngine(Path(db_path))
            self._owns_engine = True

    def close(self) -> None:
        if self._owns_engine:
            self.engine.close()

    def get_or_create_session(
        self,
        session_id: str,
        user_id: int,
        role: str,
        system_prompt: str,
        model: str,
    ) -> AssistantSessionRecord:
        record = self.engine.get_or_create_session(
            session_id=session_id,
            system_prompt=system_prompt,
            model=model,
            user_id=user_id,
            role=role,
        )
        if record.user_id is not None and record.user_id != user_id:
            raise AccessDeniedError(
                f"acceso denegado: la sesión pertenece al usuario {record.user_id}"
            )
        current_role = record.role if record.role is not None else role
        if record.role is not None and record.role != role:
            with self.engine._transaction() as conn:
                conn.execute(
                    "UPDATE sessions SET role = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE session_id = ?",
                    (role, session_id),
                )
            current_role = role
        return AssistantSessionRecord(
            session_id=record.session_id,
            user_id=record.user_id if record.user_id is not None else user_id,
            role=current_role,
            model=record.model,
            system_prompt_hash=record.system_prompt_hash,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _check_access(self, session_id: str, user_id: int, role: str) -> None:
        with self.engine._reader() as connection:
            row = connection.execute(
                "SELECT user_id, role FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return
        owner_id = row["user_id"]
        if owner_id is not None and owner_id != user_id:
            raise AccessDeniedError(
                f"acceso denegado: usuario {user_id} intentó acceder a sesión de usuario {owner_id}"
            )
        if row["role"] is not None and row["role"] != role:
            with self.engine._transaction() as conn:
                conn.execute(
                    "UPDATE sessions SET role = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE session_id = ?",
                    (role, session_id),
                )

    def record_turn(
        self,
        session_id: str,
        user_id: int,
        role: str,
        user_prompt: str,
        assistant_response: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        self._check_access(session_id, user_id, role)
        self.engine.append_messages(
            session_id,
            [
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": assistant_response},
            ],
        )
        if prompt_tokens > 0 or completion_tokens > 0:
            self.engine.record_usage(
                session_id,
                model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

    def get_transcript(
        self,
        session_id: str,
        user_id: int,
        role: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self._check_access(session_id, user_id, role)
        records = self.engine.get_session_transcript(session_id, limit=limit)
        return [
            {
                "role": r.role,
                "content": r.content,
                "created_at": r.created_at,
            }
            for r in records
        ]

    def list_sessions_for_user(
        self,
        user_id: int,
        role: str,
    ) -> list[AssistantSessionRecord]:
        with self.engine._reader() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [
            AssistantSessionRecord(
                session_id=str(r["session_id"]),
                user_id=int(r["user_id"]),
                role=str(r["role"]),
                model=str(r["model"]),
                system_prompt_hash=str(r["system_prompt_hash"]),
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    def get_usage(self, session_id: str, model: str) -> dict[str, int] | None:
        return self.engine.get_usage(session_id, model)

    def save_summary(self, session_id: str, summary: str) -> None:
        self.engine.save_summary(session_id, summary)

    def get_latest_summary(self, session_id: str) -> str | None:
        return self.engine.get_latest_summary(session_id)


__all__ = ["AccessDeniedError", "AssistantMemory", "AssistantSessionRecord"]
