import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    message_id: int
    session_id: str
    role: str
    content: str
    rank: float


def search_history(
    connection: sqlite3.Connection, query: str, limit: int = 10, session_id: str | None = None
) -> list[SearchResult]:
    if limit < 1 or limit > 100:
        raise ValueError("limit debe estar entre 1 y 100")
    text = query.strip()
    if len(text) < 3:
        return []
    # Treat user text as a literal phrase, never as FTS operators or SQL.
    phrase = '"' + text.replace('"', '""') + '"'
    sql = (
        "SELECT m.id, m.session_id, m.role, m.content, bm25(messages_fts) AS rank "
        "FROM messages_fts JOIN messages m ON m.id=messages_fts.rowid "
        "WHERE messages_fts MATCH ? "
    )
    parameters: list[object] = [phrase]
    if session_id is not None:
        sql += "AND m.session_id = ? "
        parameters.append(session_id)
    sql += "ORDER BY rank, m.id LIMIT ?"
    parameters.append(limit)
    rows = connection.execute(sql, parameters).fetchall()
    return [SearchResult(int(row[0]), row[1], row[2], row[3], float(row[4])) for row in rows]
