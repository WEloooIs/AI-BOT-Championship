from __future__ import annotations

from typing import Any

from .sqlite_store import SQLiteStore


class RepositoryBundle:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def upsert(self, table: str, data: dict[str, Any], json_fields: set[str] | None = None) -> None:
        json_fields = json_fields or set()
        converted = {}
        for key, value in data.items():
            converted[key] = self.store.dumps(value) if key in json_fields else value
        columns = ", ".join(converted.keys())
        placeholders = ", ".join(f":{key}" for key in converted.keys())
        update_clause = ", ".join(f"{key}=excluded.{key}" for key in converted.keys())
        with self.store.connection() as conn:
            conn.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT DO UPDATE SET {update_clause}",
                converted,
            )

    def replace_blockers(self, match_id: str, version: int, blockers: list[dict[str, Any]]) -> None:
        with self.store.connection() as conn:
            conn.execute(
                "DELETE FROM match_start_blockers WHERE match_id = ? AND match_context_version = ?",
                (match_id, version),
            )
            for blocker in blockers:
                conn.execute(
                    """
                    INSERT INTO match_start_blockers (
                        match_id, match_context_version, code, severity, message,
                        bot_id, team_id, recoverable, suggested_action
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match_id,
                        version,
                        blocker["code"],
                        blocker["severity"],
                        blocker["message"],
                        blocker.get("bot_id"),
                        blocker.get("team_id"),
                        1 if blocker.get("recoverable", True) else 0,
                        blocker.get("suggested_action"),
                    ),
                )

    def append_event(
        self,
        *,
        timestamp: str,
        event_type: str,
        entity_type: str | None,
        entity_id: str | None,
        match_id: str | None,
        match_context_version: int | None,
        error_code: str | None,
        payload: dict[str, Any],
    ) -> None:
        with self.store.connection() as conn:
            conn.execute(
                """
                INSERT INTO coordinator_event_log (
                    timestamp, event_type, entity_type, entity_id, match_id,
                    match_context_version, error_code, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    event_type,
                    entity_type,
                    entity_id,
                    match_id,
                    match_context_version,
                    error_code,
                    self.store.dumps(payload),
                ),
            )

    def fetch_one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.store.connection() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.store.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
