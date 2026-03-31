from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS bots (
                    bot_id TEXT PRIMARY KEY,
                    instance_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    assigned_team_id TEXT,
                    assigned_role TEXT,
                    logic_version TEXT NOT NULL,
                    config_version TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bot_runtime_status (
                    bot_id TEXT PRIMARY KEY,
                    match_id TEXT,
                    match_context_version INTEGER NOT NULL,
                    process_state TEXT NOT NULL,
                    workflow_state TEXT NOT NULL,
                    selected_brawler TEXT,
                    last_heartbeat_at TEXT,
                    last_error_code TEXT,
                    last_error_reason TEXT,
                    responsive INTEGER NOT NULL,
                    active_pid INTEGER,
                    command_id TEXT,
                    extras_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS teams (
                    team_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    color TEXT NOT NULL,
                    bot_ids_json TEXT NOT NULL,
                    roles_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tournaments (
                    tournament_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    team_ids_json TEXT NOT NULL,
                    current_match_id TEXT,
                    winner_team_id TEXT,
                    created_at TEXT,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS tournament_stages (
                    stage_id TEXT PRIMARY KEY,
                    tournament_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    match_id TEXT,
                    winner_team_id TEXT
                );
                CREATE TABLE IF NOT EXISTS matches (
                    match_id TEXT PRIMARY KEY,
                    tournament_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    mode TEXT,
                    map_name TEXT,
                    best_of INTEGER NOT NULL,
                    team_a_id TEXT NOT NULL,
                    team_b_id TEXT NOT NULL,
                    match_context_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    winner_team_id TEXT
                );
                CREATE TABLE IF NOT EXISTS draft_plans (
                    draft_id TEXT PRIMARY KEY,
                    match_id TEXT NOT NULL,
                    match_context_version INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    map_name TEXT NOT NULL,
                    team_a_final_json TEXT NOT NULL,
                    team_b_final_json TEXT NOT NULL,
                    team_a_packages_json TEXT NOT NULL DEFAULT '[]',
                    team_b_packages_json TEXT NOT NULL DEFAULT '[]',
                    meta_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    source_provider TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    generated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pick_assignments (
                    assignment_id TEXT PRIMARY KEY,
                    match_id TEXT NOT NULL,
                    match_context_version INTEGER NOT NULL,
                    team_id TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    brawler TEXT NOT NULL,
                    state TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    started_at TEXT,
                    confirmed_at TEXT,
                    pick_package_json TEXT NOT NULL DEFAULT '{}',
                    loadout_state TEXT NOT NULL DEFAULT 'loadout_not_requested',
                    loadout_result_json TEXT NOT NULL DEFAULT '{}',
                    failure_code TEXT,
                    failure_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS match_runtime_attachments (
                    match_id TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    instance_serial TEXT NOT NULL,
                    instance_label TEXT NOT NULL,
                    vendor TEXT NOT NULL,
                    model TEXT,
                    port INTEGER,
                    match_confidence REAL NOT NULL,
                    attached_at TEXT NOT NULL,
                    attached_by TEXT,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (match_id, bot_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_match_runtime_instance_unique
                ON match_runtime_attachments(match_id, instance_serial);
                CREATE TABLE IF NOT EXISTS command_executions (
                    command_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    command_type TEXT NOT NULL,
                    target_bot_id TEXT,
                    match_id TEXT,
                    match_context_version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    accepted_at TEXT,
                    completed_at TEXT,
                    failure_code TEXT,
                    failure_reason TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_commands_idempotency
                ON command_executions(idempotency_key);
                CREATE TABLE IF NOT EXISTS manual_overrides (
                    override_id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    target_entity TEXT NOT NULL,
                    effect TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS match_start_blockers (
                    blocker_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id TEXT NOT NULL,
                    match_context_version INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    bot_id TEXT,
                    team_id TEXT,
                    recoverable INTEGER NOT NULL,
                    suggested_action TEXT
                );
                CREATE TABLE IF NOT EXISTS communication_messages (
                    message_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    match_id TEXT NOT NULL,
                    match_context_version INTEGER NOT NULL,
                    team_id TEXT NOT NULL,
                    from_bot_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    urgency TEXT NOT NULL,
                    ttl_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS observer_notes (
                    note_id TEXT PRIMARY KEY,
                    match_id TEXT NOT NULL,
                    match_context_version INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS narrative_events (
                    event_id TEXT PRIMARY KEY,
                    match_id TEXT NOT NULL,
                    match_context_version INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    team_focus TEXT,
                    confidence REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS highlight_candidates (
                    highlight_id TEXT PRIMARY KEY,
                    match_id TEXT NOT NULL,
                    match_context_version INTEGER NOT NULL,
                    timestamp_start REAL NOT NULL,
                    timestamp_end REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    priority_score REAL NOT NULL,
                    team_focus TEXT,
                    short_title TEXT NOT NULL,
                    short_summary TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mvp_scores (
                    score_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id TEXT NOT NULL,
                    match_context_version INTEGER NOT NULL,
                    bot_id TEXT NOT NULL,
                    objective_score REAL NOT NULL,
                    pressure_score REAL NOT NULL,
                    survival_score REAL NOT NULL,
                    clutch_score REAL NOT NULL,
                    stability_score REAL NOT NULL,
                    total_score REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS match_reports (
                    match_id TEXT PRIMARY KEY,
                    tournament_id TEXT NOT NULL,
                    match_context_version INTEGER NOT NULL,
                    report_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS control_plane_health (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    coordinator_alive INTEGER NOT NULL,
                    database_writable INTEGER NOT NULL,
                    observer_healthy INTEGER NOT NULL,
                    last_checked_at TEXT NOT NULL,
                    degraded_reasons_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS coordinator_event_log (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    entity_type TEXT,
                    entity_id TEXT,
                    match_id TEXT,
                    match_context_version INTEGER,
                    error_code TEXT,
                    payload_json TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "draft_plans", "team_a_packages_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "draft_plans", "team_b_packages_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "draft_plans", "meta_snapshot_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "pick_assignments", "pick_package_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "pick_assignments", "loadout_state", "TEXT NOT NULL DEFAULT 'loadout_not_requested'")
            self._ensure_column(conn, "pick_assignments", "loadout_result_json", "TEXT NOT NULL DEFAULT '{}'")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column in existing:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def loads(value: str | None, default: Any) -> Any:
        if not value:
            return default
        return json.loads(value)
