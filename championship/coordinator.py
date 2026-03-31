from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from championship.draft.brawlify_provider import BrawlifyEventsProvider
from championship.draft.draft_builder import DraftBuilder
from championship.draft.static_meta_provider import StaticMetaProvider
from championship.enums import (
    BlockerSeverity,
    BotProcessState,
    BotWorkflowState,
    CommandLifecycleState,
    LoadoutLifecycleState,
    MatchStage,
    MatchStatus,
    PickLifecycleState,
    TournamentState,
)
from championship.error_codes import (
    BRAWLER_PICK_FAILED,
    BRAWLIFY_FETCH_FAILED,
    BOT_NOT_ATTACHED_TO_ACTIVE_MATCH,
    BOT_RUNTIME_MISSING_FOR_ACTIVE_MATCH,
    BOT_UNRESPONSIVE,
    COMMAND_TARGET_MISSING,
    DATABASE_NOT_WRITABLE,
    FRIENDLY_LOBBY_NOT_DETECTED,
    GADGET_SET_FAILED,
    GEAR_SET_FAILED,
    HOST_NOT_AVAILABLE,
    HYPERCHARGE_SETUP_FAILED,
    LOBBY_JOIN_FAILED,
    LOBBY_NOT_ESTABLISHED,
    LOADOUT_NOT_CONFIRMED,
    LOADOUT_SCREEN_NOT_OPENED,
    LOADOUT_VERIFIED_PARTIAL,
    MATCHMAKING_NOT_STARTED,
    MATCHMAKING_NOT_ENTERED,
    MATCH_START_NOT_CONFIRMED,
    PICK_CONFIRM_TIMEOUT,
    READY_CHECK_FAILED,
    REPORT_BUILD_FAILED,
    RUNTIME_ATTACHMENT_CONFLICT,
    STAR_POWER_SET_FAILED,
    STALE_CONTEXT_CONFIRMATION,
    STALE_RUNTIME_PAYLOAD,
    WORKER_LAUNCH_FAILED,
)
from championship.health import build_health
from championship.loadout_state import (
    is_loadout_ready,
    loadout_result_for_assignment,
    loadout_state_for_assignment,
    loadout_warning_state,
    pick_requires_loadout,
)
from championship.models import MatchReport, to_plain_dict
from championship.observer.observer_service import ObserverService
from championship.persistence.artifact_exporter import ArtifactExporter
from championship.persistence.repositories import RepositoryBundle
from championship.persistence.sqlite_store import SQLiteStore
from championship.platform import get_platform_adapter
from championship.preflight import derive_match_start_blockers
from championship.runtime.instance_discovery import detect_instances
from championship.runtime.ready_validator import is_runtime_ready
from championship.runtime.status_tracker import classify_process_state
from championship.teams.party_manager import PartyManager
from championship.teams.role_assignment import default_roles
from championship.tournament.tournament_manager import TournamentManager
from instance_identity import KNOWN_TEAM_TAGS


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "championship_data"
DB_PATH = DATA_DIR / "championship.sqlite"
RUNTIME_SCRIPT = BASE_DIR / "pyla_balanced_main.py"
POLICY_TICK_SECONDS = 2.0
PICK_CONFIRM_TIMEOUT_SECONDS = 30.0
RELAUNCH_COOLDOWN_SECONDS = 12.0
MAX_PREMATCH_RELAUNCH_ATTEMPTS = 2
MATCH_START_TIMEOUT_SECONDS = 25.0


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def row_json(row: dict[str, Any], key: str, default: Any) -> Any:
    value = row.get(key)
    if not value:
        return default
    return json.loads(value)


COORDINATOR_API_VERSION = "2026-03-30-runtime-attach"


class ChampionshipCoordinator:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(DB_PATH)
        self.repos = RepositoryBundle(self.store)
        self.exporter = ArtifactExporter(DATA_DIR)
        self.party_manager = PartyManager()
        self.tournament_manager = TournamentManager()
        self.draft_builder = DraftBuilder(BrawlifyEventsProvider(fallback_provider=StaticMetaProvider()))
        self.observer = ObserverService()
        self._lock = threading.RLock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._bot_processes: dict[str, subprocess.Popen[str]] = {}
        self._bot_log_handles: dict[str, Any] = {}
        self._last_draft_signatures: set[str] = set()
        self._policy_thread: threading.Thread | None = None
        self._policy_stop = threading.Event()
        self._match_runtime_meta: dict[str, dict[str, Any]] = {}
        self._touch_health()

    def _touch_health(self) -> None:
        degraded: list[str] = []
        try:
            database_writable = True
            with self.store.connection() as conn:
                conn.execute("SELECT 1")
        except Exception:
            database_writable = False
            degraded.append(DATABASE_NOT_WRITABLE)
        health = build_health(database_writable, self.observer.healthy, degraded)
        self.repos.upsert(
            "control_plane_health",
            {
                "singleton_id": 1,
                "coordinator_alive": 1 if health.coordinator_alive else 0,
                "database_writable": 1 if health.database_writable else 0,
                "observer_healthy": 1 if health.observer_healthy else 0,
                "last_checked_at": health.last_checked_at,
                "degraded_reasons_json": health.degraded_reasons,
            },
            {"degraded_reasons_json"},
        )

    def _log_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        match_id: str | None = None,
        match_context_version: int | None = None,
        error_code: str | None = None,
    ) -> None:
        self.repos.append_event(
            timestamp=now_iso(),
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            match_id=match_id,
            match_context_version=match_context_version,
            error_code=error_code,
            payload=payload,
        )

    def _load_bots(self) -> list[dict[str, Any]]:
        rows = self.repos.fetch_all("SELECT * FROM bots ORDER BY display_name, bot_id")
        for row in rows:
            row["metadata"] = row_json(row, "metadata_json", {})
        return rows

    def _load_runtime_statuses(self) -> dict[str, dict[str, Any]]:
        rows = self.repos.fetch_all("SELECT * FROM bot_runtime_status")
        data: dict[str, dict[str, Any]] = {}
        for row in rows:
            row["responsive"] = bool(row["responsive"])
            row["extras"] = row_json(row, "extras_json", {})
            data[row["bot_id"]] = row
        return data

    def _load_teams(self) -> list[dict[str, Any]]:
        rows = self.repos.fetch_all("SELECT * FROM teams ORDER BY name, team_id")
        for row in rows:
            row["bot_ids"] = row_json(row, "bot_ids_json", [])
            row["roles"] = row_json(row, "roles_json", {})
        return rows

    def _load_current_tournament(self) -> dict[str, Any] | None:
        row = self.repos.fetch_one("SELECT * FROM tournaments ORDER BY created_at DESC LIMIT 1")
        if not row:
            return None
        row["team_ids"] = row_json(row, "team_ids_json", [])
        return row

    def _load_match(self, match_id: str) -> dict[str, Any] | None:
        return self.repos.fetch_one("SELECT * FROM matches WHERE match_id = ?", (match_id,))

    def _load_current_match(self) -> dict[str, Any] | None:
        tournament = self._load_current_tournament()
        if not tournament or not tournament.get("current_match_id"):
            return None
        return self._load_match(tournament["current_match_id"])

    def _load_latest_draft(self, match_id: str, version: int | None = None) -> dict[str, Any] | None:
        params: tuple[Any, ...]
        if version is None:
            query = (
                "SELECT * FROM draft_plans WHERE match_id = ? "
                "ORDER BY match_context_version DESC, generated_at DESC LIMIT 1"
            )
            params = (match_id,)
        else:
            query = (
                "SELECT * FROM draft_plans WHERE match_id = ? AND match_context_version = ? "
                "ORDER BY generated_at DESC LIMIT 1"
            )
            params = (match_id, version)
        row = self.repos.fetch_one(query, params)
        if not row:
            return None
        row["team_a_final"] = row_json(row, "team_a_final_json", [])
        row["team_b_final"] = row_json(row, "team_b_final_json", [])
        row["team_a_packages"] = row_json(row, "team_a_packages_json", [])
        row["team_b_packages"] = row_json(row, "team_b_packages_json", [])
        row["meta_snapshot"] = row_json(row, "meta_snapshot_json", {})
        return row

    def _load_pick_assignments(self, match_id: str, version: int) -> dict[str, dict[str, Any]]:
        rows = self.repos.fetch_all(
            "SELECT * FROM pick_assignments WHERE match_id = ? AND match_context_version = ?",
            (match_id, version),
        )
        for row in rows:
            row["pick_package"] = row_json(row, "pick_package_json", {})
            row["loadout_result"] = row_json(row, "loadout_result_json", {})
        return {row["bot_id"]: row for row in rows}

    def _load_match_attachments(self, match_id: str) -> dict[str, dict[str, Any]]:
        rows = self.repos.fetch_all(
            "SELECT * FROM match_runtime_attachments WHERE match_id = ? ORDER BY attached_at, bot_id",
            (match_id,),
        )
        attachments: dict[str, dict[str, Any]] = {}
        for row in rows:
            row["metadata"] = row_json(row, "metadata_json", {})
            attachments[row["bot_id"]] = row
        return attachments

    def _load_attachment_for_bot(self, match_id: str, bot_id: str) -> dict[str, Any] | None:
        row = self.repos.fetch_one(
            "SELECT * FROM match_runtime_attachments WHERE match_id = ? AND bot_id = ?",
            (match_id, bot_id),
        )
        if not row:
            return None
        row["metadata"] = row_json(row, "metadata_json", {})
        return row

    def _delete_attachment(self, match_id: str, bot_id: str) -> None:
        with self.store.connection() as conn:
            conn.execute(
                "DELETE FROM match_runtime_attachments WHERE match_id = ? AND bot_id = ?",
                (match_id, bot_id),
            )

    def _load_match_teams(self, match_row: dict[str, Any]) -> list[dict[str, Any]]:
        teams_lookup = {row["team_id"]: row for row in self._load_teams()}
        return [
            teams_lookup.get(match_row["team_a_id"], {"team_id": match_row["team_a_id"], "name": "Team A", "bot_ids": [], "roles": {}}),
            teams_lookup.get(match_row["team_b_id"], {"team_id": match_row["team_b_id"], "name": "Team B", "bot_ids": [], "roles": {}}),
        ]

    def _match_bot_ids(self, match_row: dict[str, Any]) -> list[str]:
        bot_ids: list[str] = []
        for team in self._load_match_teams(match_row):
            bot_ids.extend(list(team.get("bot_ids", [])))
        seen: set[str] = set()
        ordered: list[str] = []
        for bot_id in bot_ids:
            if bot_id and bot_id not in seen:
                seen.add(bot_id)
                ordered.append(bot_id)
        return ordered

    def _load_match_blockers(self, match_id: str, version: int) -> list[dict[str, Any]]:
        return self.repos.fetch_all(
            "SELECT * FROM match_start_blockers WHERE match_id = ? AND match_context_version = ? ORDER BY blocker_id",
            (match_id, version),
        )

    def _replace_blockers(self, match_row: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
        self.repos.replace_blockers(match_row["match_id"], int(match_row["match_context_version"]), blockers)

    def _stop_bot_process(self, bot_id: str) -> None:
        process = self._bot_processes.pop(bot_id, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except Exception:
                process.kill()
        handle = self._bot_log_handles.pop(bot_id, None)
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass

    def _upsert_runtime_status(self, data: dict[str, Any]) -> None:
        payload = dict(data)
        payload.setdefault("extras_json", {})
        self.repos.upsert("bot_runtime_status", payload, {"extras_json"})

    def _set_match_status(
        self,
        match_row: dict[str, Any],
        status: str,
        *,
        touch_start: bool = False,
        touch_end: bool = False,
    ) -> dict[str, Any]:
        updated = dict(match_row)
        updated["status"] = status
        if touch_start and not updated.get("start_time"):
            updated["start_time"] = now_iso()
        if touch_end:
            updated["end_time"] = now_iso()
        self.repos.upsert("matches", updated)
        return updated

    def _set_tournament_status(self, state: str) -> None:
        tournament = self._load_current_tournament()
        if not tournament:
            return
        self._persist_tournament(tournament, status=state)

    def _persist_tournament(self, tournament: dict[str, Any], **updates: Any) -> None:
        payload = dict(tournament)
        payload.update(updates)
        team_ids = payload.pop("team_ids", None)
        payload["team_ids_json"] = team_ids if team_ids is not None else row_json(tournament, "team_ids_json", [])
        self.repos.upsert("tournaments", payload, {"team_ids_json"})

    def _runtime_command_mismatch(
        self,
        current_status: dict[str, Any],
        *,
        match_id: str | None,
        version: int,
        command_id: str | None,
    ) -> bool:
        current_match_id = current_status.get("match_id")
        current_version = int(current_status.get("match_context_version", 0))
        current_command_id = current_status.get("command_id")
        if current_match_id and match_id and current_match_id == match_id and current_version > version:
            return True
        if current_match_id and match_id and current_match_id == match_id and current_version == version:
            if current_command_id and command_id and current_command_id != command_id:
                return True
        return False

    def _is_stale_runtime_payload(self, payload: dict[str, Any]) -> bool:
        bot_id = payload.get("bot_id")
        match_id = payload.get("match_id")
        version = int(payload.get("match_context_version", 0) or 0)
        current_status = self.repos.fetch_one("SELECT * FROM bot_runtime_status WHERE bot_id = ?", (bot_id,)) or {}
        if self._runtime_command_mismatch(
            current_status,
            match_id=match_id,
            version=version,
            command_id=payload.get("command_id"),
        ):
            self._log_event(
                "stale_runtime_payload",
                payload,
                entity_type="bot",
                entity_id=bot_id,
                match_id=match_id,
                match_context_version=version,
                error_code=STALE_RUNTIME_PAYLOAD,
            )
            return True
        current_match = self._load_current_match()
        if current_match and match_id == current_match["match_id"] and version < int(current_match["match_context_version"]):
            self._log_event(
                "stale_runtime_payload",
                payload,
                entity_type="bot",
                entity_id=bot_id,
                match_id=match_id,
                match_context_version=version,
                error_code=STALE_RUNTIME_PAYLOAD,
            )
            return True
        return False

    def _reset_runtime_for_context(self, match_row: dict[str, Any], version: int) -> None:
        for bot_id in self._match_bot_ids(match_row):
            runtime = self.repos.fetch_one("SELECT * FROM bot_runtime_status WHERE bot_id = ?", (bot_id,)) or {}
            self._upsert_runtime_status(
                {
                    "bot_id": bot_id,
                    "match_id": match_row["match_id"],
                    "match_context_version": version,
                    "process_state": runtime.get("process_state", BotProcessState.INACTIVE),
                    "workflow_state": BotWorkflowState.NOT_READY,
                    "selected_brawler": None,
                    "last_heartbeat_at": runtime.get("last_heartbeat_at"),
                    "last_error_code": None,
                    "last_error_reason": None,
                    "responsive": int(runtime.get("responsive", 0)),
                    "active_pid": runtime.get("active_pid"),
                    "command_id": runtime.get("command_id"),
                    "extras_json": row_json(runtime, "extras_json", {}),
                }
            )

    def _mark_recovery_attempt(self, bot_id: str, reason: str) -> dict[str, Any]:
        runtime = self.repos.fetch_one("SELECT * FROM bot_runtime_status WHERE bot_id = ?", (bot_id,)) or {"bot_id": bot_id}
        extras = row_json(runtime, "extras_json", {})
        recovery = extras.get("recovery", {})
        attempts = dict(recovery.get("attempts", {}))
        attempts[reason] = int(attempts.get(reason, 0)) + 1
        recovery["attempts"] = attempts
        recovery["last_reason"] = reason
        recovery["last_attempt_at"] = now_iso()
        extras["recovery"] = recovery
        self._upsert_runtime_status(
            {
                "bot_id": bot_id,
                "match_id": runtime.get("match_id"),
                "match_context_version": int(runtime.get("match_context_version", 0)),
                "process_state": runtime.get("process_state", BotProcessState.INACTIVE),
                "workflow_state": runtime.get("workflow_state", BotWorkflowState.NOT_READY),
                "selected_brawler": runtime.get("selected_brawler"),
                "last_heartbeat_at": runtime.get("last_heartbeat_at"),
                "last_error_code": runtime.get("last_error_code"),
                "last_error_reason": runtime.get("last_error_reason"),
                "responsive": int(runtime.get("responsive", 0)),
                "active_pid": runtime.get("active_pid"),
                "command_id": runtime.get("command_id"),
                "extras_json": extras,
            }
        )
        return recovery

    def _can_attempt_relaunch(self, bot_id: str, reason: str) -> bool:
        runtime = self.repos.fetch_one("SELECT * FROM bot_runtime_status WHERE bot_id = ?", (bot_id,)) or {}
        extras = row_json(runtime, "extras_json", {})
        recovery = extras.get("recovery", {})
        attempts = int(recovery.get("attempts", {}).get(reason, 0))
        if attempts >= MAX_PREMATCH_RELAUNCH_ATTEMPTS:
            return False
        last_attempt = parse_iso(recovery.get("last_attempt_at"))
        if last_attempt and (datetime.now(UTC) - last_attempt).total_seconds() < RELAUNCH_COOLDOWN_SECONDS:
            return False
        return True

    def _current_ready_bots(self, match_row: dict[str, Any]) -> list[str]:
        version = int(match_row["match_context_version"])
        assignments = self._load_pick_assignments(match_row["match_id"], version)
        attachments = self._load_match_attachments(match_row["match_id"])
        statuses = self._load_runtime_statuses()
        ready: list[str] = []
        for bot_id in self._match_bot_ids(match_row):
            if bot_id not in attachments:
                continue
            assignment = assignments.get(bot_id)
            status = statuses.get(bot_id, {})
            if assignment and assignment.get("state") == PickLifecycleState.CONFIRMED and is_loadout_ready(assignment) and is_runtime_ready(status, version):
                ready.append(bot_id)
        return ready

    def _default_friendly_host_bot_id(self, match_row: dict[str, Any]) -> str | None:
        teams = self._load_match_teams(match_row)
        if not teams:
            return None
        bot_ids = list(teams[0].get("bot_ids", []))
        return bot_ids[0] if bot_ids else None

    def _friendly_host_bot_id(self, match_row: dict[str, Any]) -> str | None:
        meta = self._match_runtime_meta.get(match_row["match_id"], {})
        host_bot_id = meta.get("host_bot_id")
        return host_bot_id or self._default_friendly_host_bot_id(match_row)

    def _friendly_snapshot(self, runtime_status: dict[str, Any]) -> dict[str, Any]:
        extras = runtime_status.get("extras")
        if extras is None:
            extras = row_json(runtime_status, "extras_json", {})
        snapshot = extras.get("friendly_flow", {})
        return snapshot if isinstance(snapshot, dict) else {}

    def _is_host_candidate_ready(
        self,
        *,
        bot_id: str,
        status: dict[str, Any],
        assignment: dict[str, Any] | None,
        version: int,
    ) -> bool:
        if not assignment or assignment.get("state") != PickLifecycleState.CONFIRMED:
            return False
        if not is_loadout_ready(assignment):
            return False
        if int(status.get("match_context_version", -1)) != version:
            return False
        if status.get("process_state") not in {BotProcessState.ACTIVE, BotProcessState.STALE}:
            return False
        if not status.get("responsive"):
            return False
        if status.get("workflow_state") not in {
            BotWorkflowState.BRAWLER_SELECTED,
            BotWorkflowState.IN_LOBBY,
            BotWorkflowState.MATCHMAKING,
        }:
            return False
        snapshot = self._friendly_snapshot(status)
        if snapshot and not snapshot.get("lobby_established") and status.get("workflow_state") != BotWorkflowState.MATCHMAKING:
            return False
        return True

    def _retarget_start_command(
        self,
        *,
        previous_host: str | None,
        new_host: str,
        match_row: dict[str, Any],
        meta: dict[str, Any],
    ) -> None:
        previous_command = self._load_command(meta.get("start_command_id"))
        if previous_command and previous_command.get("state") in {
            CommandLifecycleState.ISSUED,
            CommandLifecycleState.ACCEPTED,
        }:
            self.update_command(
                {
                    "command_id": previous_command["command_id"],
                    "state": CommandLifecycleState.FAILED,
                    "failure_code": HOST_NOT_AVAILABLE,
                    "failure_reason": f"Host failover from {previous_host} to {new_host}.",
                }
            )
        meta["start_command_id"] = None
        meta["matchmaking_entered_logged"] = False
        meta["matchmaking_entered_at"] = None
        meta["host_bot_id"] = new_host
        self._log_event(
            "host_failover_selected",
            {
                "match_id": match_row["match_id"],
                "previous_host_bot_id": previous_host,
                "new_host_bot_id": new_host,
            },
            entity_type="match",
            entity_id=match_row["match_id"],
            match_id=match_row["match_id"],
            match_context_version=int(match_row["match_context_version"]),
        )

    def _select_host_for_start(
        self,
        match_row: dict[str, Any],
        statuses: dict[str, dict[str, Any]],
        assignments: dict[str, dict[str, Any]],
    ) -> str | None:
        version = int(match_row["match_context_version"])
        meta = self._match_runtime_meta.setdefault(match_row["match_id"], {})
        current_host = self._friendly_host_bot_id(match_row)
        attachments = self._load_match_attachments(match_row["match_id"])
        team_a = self._load_match_teams(match_row)[0] if self._load_match_teams(match_row) else {"bot_ids": []}
        candidates = []
        for index, bot_id in enumerate(list(team_a.get("bot_ids", []))):
            if bot_id not in attachments:
                continue
            if not self._is_host_candidate_ready(
                bot_id=bot_id,
                status=statuses.get(bot_id, {}),
                assignment=assignments.get(bot_id),
                version=version,
            ):
                continue
            snapshot = self._friendly_snapshot(statuses.get(bot_id, {}))
            score = 0
            if bot_id == current_host:
                score += 2
            if snapshot.get("expected_lobby_state"):
                score += 3
            if snapshot.get("start_button_visible"):
                score += 4
            if snapshot.get("lobby_established"):
                score += 2
            score -= index
            candidates.append((score, bot_id))

        if not candidates:
            meta["host_bot_id"] = None
            return None

        candidates.sort(reverse=True)
        new_host = candidates[0][1]
        if current_host != new_host:
            self._retarget_start_command(
                previous_host=current_host,
                new_host=new_host,
                match_row=match_row,
                meta=meta,
            )
        else:
            meta["host_bot_id"] = new_host
        return new_host

    def _recent_match_events(self, match_id: str, version: int, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.repos.fetch_all(
            """
            SELECT * FROM coordinator_event_log
            WHERE match_id = ?
              AND (match_context_version = ? OR match_context_version IS NULL)
            ORDER BY event_id DESC
            LIMIT ?
            """,
            (match_id, version, limit),
        )
        decoded: list[dict[str, Any]] = []
        for row in rows:
            row["payload"] = row_json(row, "payload_json", {})
            decoded.append(row)
        return decoded

    def _build_handshake_diagnostics(
        self,
        match_row: dict[str, Any],
        statuses: dict[str, dict[str, Any]],
        assignments: dict[str, dict[str, Any]],
        blockers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        version = int(match_row["match_context_version"])
        ready_bots = set(self._current_ready_bots(match_row))
        default_host = self._default_friendly_host_bot_id(match_row)
        host_bot_id = self._friendly_host_bot_id(match_row)
        attachments = self._load_match_attachments(match_row["match_id"])
        bot_rows: list[dict[str, Any]] = []
        teams = {team["team_id"]: team for team in self._load_match_teams(match_row)}
        host_snapshot = self._friendly_snapshot(statuses.get(host_bot_id or "", {}))

        for team_id, team in teams.items():
            for bot_id in list(team.get("bot_ids", [])):
                status = statuses.get(bot_id, {})
                assignment = assignments.get(bot_id)
                attachment = attachments.get(bot_id)
                snapshot = self._friendly_snapshot(status)
                missing: list[str] = []
                step = "ready"
                if not attachment:
                    step = "runtime_not_attached"
                    missing.append("live_runtime_attachment")
                elif status.get("process_state") not in {BotProcessState.ACTIVE, BotProcessState.STALE}:
                    step = "runtime_unavailable"
                    missing.append("runtime_alive")
                elif int(status.get("match_context_version", -1)) != version:
                    step = "stale_context"
                    missing.append("current_match_context")
                elif not assignment:
                    step = "pick_assignment_missing"
                    missing.append("pick_assignment")
                elif assignment.get("state") != PickLifecycleState.CONFIRMED:
                    step = "waiting_pick_confirmation"
                    missing.append("pick_confirmed")
                elif not is_loadout_ready(assignment):
                    step = "waiting_loadout_confirmation"
                    missing.append("loadout_confirmed")
                elif not snapshot and match_row["status"] in {MatchStatus.READY_CHECK, MatchStatus.LOBBY_SETUP, MatchStatus.STARTING}:
                    step = "waiting_handshake_snapshot"
                    missing.append("friendly_flow_snapshot")
                elif match_row["status"] in {MatchStatus.READY_CHECK, MatchStatus.LOBBY_SETUP, MatchStatus.STARTING} and not snapshot.get("lobby_established"):
                    step = "waiting_lobby"
                    missing.append("lobby_established")
                elif match_row["status"] in {MatchStatus.READY_CHECK, MatchStatus.LOBBY_SETUP, MatchStatus.STARTING} and not snapshot.get("expected_lobby_state"):
                    step = "waiting_friendly_lobby"
                    missing.append("expected_friendly_lobby")
                elif bot_id == host_bot_id and match_row["status"] in {MatchStatus.LOBBY_SETUP, MatchStatus.STARTING} and not snapshot.get("start_button_visible") and not snapshot.get("matchmaking_entered"):
                    step = "waiting_host_start_trigger"
                    missing.append("start_button_visible")
                elif match_row["status"] == MatchStatus.STARTING and not snapshot.get("matchmaking_entered"):
                    step = "waiting_matchmaking"
                    missing.append("matchmaking_entered")
                elif match_row["status"] == MatchStatus.STARTING and snapshot.get("matchmaking_entered") and not snapshot.get("match_started_confirmed"):
                    step = "waiting_match_start"
                    missing.append("match_started_confirmed")
                elif status.get("workflow_state") == BotWorkflowState.IN_MATCH or snapshot.get("match_started_confirmed"):
                    step = "in_match"
                elif status.get("workflow_state") == BotWorkflowState.POST_MATCH:
                    step = "post_match"

                bot_rows.append(
                    {
                        "bot_id": bot_id,
                        "team_id": team_id,
                        "is_host": bot_id == host_bot_id,
                        "is_default_host": bot_id == default_host,
                        "process_state": status.get("process_state", BotProcessState.INACTIVE),
                        "workflow_state": status.get("workflow_state", BotWorkflowState.NOT_READY),
                        "pick_state": (assignment or {}).get("state"),
                        "loadout_state": loadout_state_for_assignment(assignment),
                        "loadout_result": loadout_result_for_assignment(assignment),
                        "selected_brawler": status.get("selected_brawler"),
                        "handshake_step": step,
                        "missing": missing,
                        "ready": bot_id in ready_bots,
                        "attachment": attachment,
                        "snapshot": snapshot,
                        "last_error_code": status.get("last_error_code"),
                        "last_error_reason": status.get("last_error_reason"),
                    }
                )

        pick_confirmed = sum(1 for row in bot_rows if row.get("pick_state") == PickLifecycleState.CONFIRMED)
        loadout_confirmed = sum(1 for row in bot_rows if is_loadout_ready(assignments.get(row["bot_id"])))
        attached_count = sum(1 for row in bot_rows if row.get("attachment"))
        lobby_seen = sum(1 for row in bot_rows if row.get("snapshot", {}).get("lobby_established"))
        matchmaking_seen = sum(1 for row in bot_rows if row.get("snapshot", {}).get("matchmaking_entered"))
        match_started = any(row.get("snapshot", {}).get("match_started_confirmed") or row.get("workflow_state") == BotWorkflowState.IN_MATCH for row in bot_rows)
        if match_row["status"] == MatchStatus.IN_MATCH:
            phase = "in_match"
        elif attached_count < len(bot_rows):
            phase = "waiting_runtime_attachments"
        elif match_row["status"] == MatchStatus.STARTING and matchmaking_seen:
            phase = "waiting_match_start_confirmation"
        elif match_row["status"] == MatchStatus.STARTING:
            phase = "waiting_matchmaking_entry"
        elif pick_confirmed < len(bot_rows):
            phase = "waiting_pick_confirmations"
        elif loadout_confirmed < len(bot_rows):
            phase = "waiting_loadout_confirmations"
        elif lobby_seen < len(bot_rows):
            phase = "waiting_lobby_established"
        else:
            phase = "ready_for_start"

        steps = [
            {
                "key": "runtime_attached",
                "label": "Runtime attached",
                "value": f"{attached_count}/{len(bot_rows)}",
                "status": "ok" if attached_count == len(bot_rows) and bot_rows else "waiting",
            },
            {
                "key": "picks_confirmed",
                "label": "Picks confirmed",
                "value": f"{pick_confirmed}/{len(bot_rows)}",
                "status": "ok" if pick_confirmed == len(bot_rows) and bot_rows else "waiting",
            },
            {
                "key": "loadout_confirmed",
                "label": "Loadouts confirmed",
                "value": f"{loadout_confirmed}/{len(bot_rows)}",
                "status": "ok" if loadout_confirmed == len(bot_rows) and bot_rows else "waiting",
            },
            {
                "key": "lobby_established",
                "label": "Lobby established",
                "value": f"{lobby_seen}/{len(bot_rows)}",
                "status": "ok" if lobby_seen == len(bot_rows) and bot_rows else "waiting",
            },
            {
                "key": "ready_bots",
                "label": "Derived ready",
                "value": f"{len(ready_bots)}/{len(bot_rows)}",
                "status": "ok" if len(ready_bots) == len(bot_rows) and bot_rows else "waiting",
            },
            {
                "key": "matchmaking_entered",
                "label": "Matchmaking entered",
                "value": f"{matchmaking_seen}/{len(bot_rows)}",
                "status": "ok" if matchmaking_seen else "waiting",
            },
            {
                "key": "match_started",
                "label": "Match started confirmed",
                "value": "yes" if match_started else "no",
                "status": "ok" if match_started else "waiting",
            },
        ]

        return {
            "phase": phase,
            "match_status": match_row["status"],
            "current_host_bot_id": host_bot_id,
            "default_host_bot_id": default_host,
            "host_failover_active": bool(host_bot_id and default_host and host_bot_id != default_host),
            "host_snapshot": host_snapshot,
            "steps": steps,
            "bots": bot_rows,
            "blocker_count": len(blockers),
            "recent_events": self._recent_match_events(match_row["match_id"], version, limit=25),
        }

    def _load_command(self, command_id: str | None) -> dict[str, Any] | None:
        if not command_id:
            return None
        row = self.repos.fetch_one("SELECT * FROM command_executions WHERE command_id = ?", (command_id,))
        if not row:
            return None
        row["payload"] = row_json(row, "payload_json", {})
        return row

    def _find_active_command(
        self,
        *,
        target_bot_id: str | None,
        match_id: str,
        match_context_version: int,
        command_type: str,
    ) -> dict[str, Any] | None:
        rows = self.repos.fetch_all(
            """
            SELECT * FROM command_executions
            WHERE target_bot_id IS ?
              AND match_id = ?
              AND match_context_version = ?
              AND command_type = ?
              AND state IN (?, ?)
            ORDER BY issued_at DESC
            """,
            (
                target_bot_id,
                match_id,
                match_context_version,
                command_type,
                CommandLifecycleState.ISSUED,
                CommandLifecycleState.ACCEPTED,
            ),
        )
        if not rows:
            return None
        row = rows[0]
        row["payload"] = row_json(row, "payload_json", {})
        return row

    def _derive_platform_blockers(
        self,
        match_row: dict[str, Any],
        statuses: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        bot_lookup = {row["bot_id"]: row for row in self._load_bots()}
        attachments = self._load_match_attachments(match_row["match_id"])
        blockers: list[dict[str, Any]] = []
        host_bot_id = self._friendly_host_bot_id(match_row)
        for team in self._load_match_teams(match_row):
            team_id = team.get("team_id")
            for bot_id in list(team.get("bot_ids", [])):
                if bot_id not in attachments:
                    continue
                status = statuses.get(bot_id, {})
                if status.get("process_state") not in {BotProcessState.ACTIVE, BotProcessState.STALE}:
                    continue
                platform_name = (bot_lookup.get(bot_id) or {}).get("platform", "nulls")
                adapter = get_platform_adapter(platform_name)
                snapshot = self._friendly_snapshot(status)
                for blocker in adapter.build_lobby_blockers(
                    bot_id=bot_id,
                    team_id=team_id,
                    snapshot=snapshot,
                    is_host=bot_id == host_bot_id,
                    match_status=match_row["status"],
                ):
                    blockers.append(to_plain_dict(blocker))
        return blockers

    def _decode_health(self) -> dict[str, Any]:
        row = self.repos.fetch_one("SELECT * FROM control_plane_health WHERE singleton_id = 1")
        if not row:
            return {
                "coordinator_alive": True,
                "database_writable": False,
                "observer_healthy": False,
                "degraded_reasons": [DATABASE_NOT_WRITABLE],
                "coordinator_version": COORDINATOR_API_VERSION,
            }
        return {
            "coordinator_alive": bool(row["coordinator_alive"]),
            "database_writable": bool(row["database_writable"]),
            "observer_healthy": bool(row["observer_healthy"]),
            "last_checked_at": row["last_checked_at"],
            "degraded_reasons": row_json(row, "degraded_reasons_json", []),
            "coordinator_version": COORDINATOR_API_VERSION,
        }

    def _refresh_process_states(self) -> None:
        statuses = self._load_runtime_statuses()
        all_bot_ids = set(statuses) | set(self._bot_processes)
        for bot_id in all_bot_ids:
            process = self._bot_processes.get(bot_id)
            has_process = bool(process and process.poll() is None)
            status = statuses.get(bot_id, {"bot_id": bot_id})
            process_state = classify_process_state(status.get("last_heartbeat_at"), has_process)
            status["process_state"] = process_state
            status["responsive"] = process_state == BotProcessState.ACTIVE
            if not has_process and process_state == BotProcessState.CRASHED:
                status["last_error_code"] = status.get("last_error_code") or WORKER_LAUNCH_FAILED
            self._upsert_runtime_status(
                {
                    "bot_id": bot_id,
                    "match_id": status.get("match_id"),
                    "match_context_version": int(status.get("match_context_version", 0)),
                    "process_state": status.get("process_state", BotProcessState.INACTIVE),
                    "workflow_state": status.get("workflow_state", BotWorkflowState.NOT_READY),
                    "selected_brawler": status.get("selected_brawler"),
                    "last_heartbeat_at": status.get("last_heartbeat_at"),
                    "last_error_code": status.get("last_error_code"),
                    "last_error_reason": status.get("last_error_reason"),
                    "responsive": 1 if status.get("responsive") else 0,
                    "active_pid": process.pid if has_process and process else None,
                    "command_id": status.get("command_id"),
                    "extras_json": status.get("extras", row_json(status, "extras_json", {})),
                }
            )

    def upsert_bot(self, payload: dict[str, Any]) -> dict[str, Any]:
        bot_id = payload.get("bot_id") or f"bot_{uuid4().hex[:8]}"
        display_name = payload.get("display_name") or bot_id
        self.repos.upsert(
            "bots",
            {
                "bot_id": bot_id,
                "instance_id": payload["instance_id"],
                "display_name": display_name,
                "platform": payload.get("platform", "nulls"),
                "assigned_team_id": payload.get("assigned_team_id"),
                "assigned_role": payload.get("assigned_role"),
                "logic_version": payload.get("logic_version", "championship-mvp"),
                "config_version": payload.get("config_version", "1"),
                "metadata_json": payload.get("metadata", {}),
            },
            {"metadata_json"},
        )
        if not self.repos.fetch_one("SELECT 1 FROM bot_runtime_status WHERE bot_id = ?", (bot_id,)):
            self.repos.upsert(
                "bot_runtime_status",
                {
                    "bot_id": bot_id,
                    "match_id": None,
                    "match_context_version": 0,
                    "process_state": BotProcessState.INACTIVE,
                    "workflow_state": BotWorkflowState.NOT_READY,
                    "selected_brawler": None,
                    "last_heartbeat_at": None,
                    "last_error_code": None,
                    "last_error_reason": None,
                    "responsive": 0,
                    "active_pid": None,
                    "command_id": None,
                    "extras_json": {},
                },
                {"extras_json"},
            )
        self._log_event("bot_upserted", payload, entity_type="bot", entity_id=bot_id)
        return {"ok": True, "bot_id": bot_id}

    def create_or_update_team(self, payload: dict[str, Any]) -> dict[str, Any]:
        team_id = payload.get("team_id") or f"team_{uuid4().hex[:6]}"
        bot_ids = self.party_manager.normalize_bot_ids(payload.get("bot_ids", []))
        roles = payload.get("roles") or default_roles(bot_ids)
        self.repos.upsert(
            "teams",
            {
                "team_id": team_id,
                "name": payload.get("name") or team_id,
                "color": payload.get("color") or "#d2452d",
                "bot_ids_json": bot_ids,
                "roles_json": roles,
            },
            {"bot_ids_json", "roles_json"},
        )
        for bot_id in bot_ids:
            existing = self.repos.fetch_one("SELECT * FROM bots WHERE bot_id = ?", (bot_id,))
            self.repos.upsert(
                "bots",
                {
                    "bot_id": bot_id,
                    "instance_id": (existing or {}).get("instance_id") or bot_id,
                    "display_name": (existing or {}).get("display_name") or bot_id,
                    "platform": (existing or {}).get("platform") or "nulls",
                    "assigned_team_id": team_id,
                    "assigned_role": roles.get(bot_id),
                    "logic_version": (existing or {}).get("logic_version") or "championship-mvp",
                    "config_version": (existing or {}).get("config_version") or "1",
                    "metadata_json": row_json(existing, "metadata_json", {}) if existing else {},
                },
                {"metadata_json"},
            )
        self._log_event("team_upserted", {"team_id": team_id, "bot_ids": bot_ids}, entity_type="team", entity_id=team_id)
        return {"ok": True, "team_id": team_id}

    def create_tournament(self, payload: dict[str, Any]) -> dict[str, Any]:
        team_ids = list(payload.get("team_ids", []))
        if len(team_ids) != 4:
            return {"ok": False, "error": "Tournament MVP requires exactly 4 teams."}
        tournament_id = payload.get("tournament_id") or f"tournament_{uuid4().hex[:8]}"
        created_at = now_iso()
        first_stage, second_stage = self.tournament_manager.build_initial_pairings(team_ids)
        first_match_id = f"match_{uuid4().hex[:8]}"
        second_match_id = f"match_{uuid4().hex[:8]}"
        final_match_id = f"match_{uuid4().hex[:8]}"

        self.repos.upsert(
            "tournaments",
            {
                "tournament_id": tournament_id,
                "name": payload.get("name") or "Bot Championship",
                "status": TournamentState.DRAFTING,
                "stage": MatchStage.SEMIFINAL_1,
                "team_ids_json": team_ids,
                "current_match_id": first_match_id,
                "winner_team_id": None,
                "created_at": created_at,
                "finished_at": None,
            },
            {"team_ids_json"},
        )
        matches = [
            (first_match_id, first_stage[0], first_stage[1], first_stage[2]),
            (second_match_id, second_stage[0], second_stage[1], second_stage[2]),
            (final_match_id, MatchStage.FINAL, "", ""),
        ]
        for match_id, stage, team_a_id, team_b_id in matches:
            self.repos.upsert(
                "matches",
                {
                    "match_id": match_id,
                    "tournament_id": tournament_id,
                    "stage": stage,
                    "mode": None,
                    "map_name": None,
                    "best_of": int(payload.get("best_of", 1)),
                    "team_a_id": team_a_id,
                    "team_b_id": team_b_id,
                    "match_context_version": 1,
                    "status": MatchStatus.DRAFTING if match_id == first_match_id else MatchStatus.PENDING,
                    "start_time": None,
                    "end_time": None,
                    "winner_team_id": None,
                },
            )
        self._log_event(
            "tournament_created",
            {"tournament_id": tournament_id, "team_ids": team_ids},
            entity_type="tournament",
            entity_id=tournament_id,
        )
        return {"ok": True, "tournament_id": tournament_id}

    def bump_match_context(self, match_id: str, reason: str) -> dict[str, Any]:
        match_row = self._load_match(match_id)
        if not match_row:
            return {"ok": False, "error": f"Unknown match_id {match_id}"}
        version = int(match_row["match_context_version"]) + 1
        default_host = self._default_friendly_host_bot_id(match_row)
        self._match_runtime_meta[match_id] = {
            "host_bot_id": default_host,
            "context_reset_reason": reason,
        }
        updated_match = {**match_row, "match_context_version": version, "status": MatchStatus.DRAFTING}
        self.repos.upsert("matches", updated_match)
        self._reset_runtime_for_context(updated_match, version)
        self.repos.replace_blockers(match_id, version, [])
        self._log_event(
            "match_context_bumped",
            {"reason": reason, "match_id": match_id, "match_context_version": version},
            entity_type="match",
            entity_id=match_id,
            match_id=match_id,
            match_context_version=version,
        )
        return {"ok": True, "match_id": match_id, "match_context_version": version}

    def update_match_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        match_id = payload["match_id"]
        match_row = self._load_match(match_id)
        if not match_row:
            return {"ok": False, "error": f"Unknown match_id {match_id}"}
        result = self.bump_match_context(match_id, payload.get("reason", "mode_map_changed"))
        version = result["match_context_version"]
        self.repos.upsert(
            "matches",
            {
                **match_row,
                "mode": payload.get("mode"),
                "map_name": payload.get("map_name"),
                "match_context_version": version,
                "status": MatchStatus.DRAFTING,
            },
        )
        draft_result = self.regenerate_draft({"match_id": match_id, "skip_context_bump": True})
        return {
            "ok": True,
            "match_id": match_id,
            "match_context_version": version,
            "draft": draft_result,
            "launch": {"ok": False, "skipped": True, "reason": "runtime_attachment_required"},
        }

    def attach_runtime_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        match_id = payload["match_id"]
        bot_id = payload["bot_id"]
        match_row = self._load_match(match_id)
        if not match_row:
            return {"ok": False, "error": f"Unknown match_id {match_id}"}
        current_match = self._load_current_match()
        if current_match and current_match.get("match_id") != match_id:
            return {"ok": False, "error": "Runtime attachments are only allowed for the current active match."}
        if bot_id not in self._match_bot_ids(match_row):
            return {"ok": False, "error": f"Bot {bot_id} is not part of match {match_id}."}
        serial = str(payload["instance_serial"])
        conflict = self.repos.fetch_one(
            """
            SELECT * FROM match_runtime_attachments
            WHERE match_id = ? AND instance_serial = ? AND bot_id != ?
            """,
            (match_id, serial, bot_id),
        )
        if conflict:
            self._log_event(
                "runtime_attach_failed",
                {
                    "match_id": match_id,
                    "bot_id": bot_id,
                    "instance_serial": serial,
                    "conflict_bot_id": conflict["bot_id"],
                },
                entity_type="match",
                entity_id=match_id,
                match_id=match_id,
                match_context_version=int(match_row["match_context_version"]),
                error_code=RUNTIME_ATTACHMENT_CONFLICT,
            )
            return {"ok": False, "error": RUNTIME_ATTACHMENT_CONFLICT}
        detected = {item["serial"]: item for item in detect_instances()}
        instance = detected.get(serial, {})
        instance_label = str(payload.get("instance_label") or instance.get("display_label") or serial)
        vendor = str(payload.get("vendor") or instance.get("vendor") or "Unknown Device")
        self.repos.upsert(
            "match_runtime_attachments",
            {
                "match_id": match_id,
                "bot_id": bot_id,
                "instance_serial": serial,
                "instance_label": instance_label,
                "vendor": vendor,
                "model": payload.get("model") or instance.get("model"),
                "port": payload.get("port") or instance.get("port"),
                "match_confidence": float(payload.get("match_confidence") or instance.get("match_confidence") or 0.0),
                "attached_at": now_iso(),
                "attached_by": payload.get("attached_by") or "hub_operator",
                "metadata_json": instance or payload.get("metadata") or {},
            },
            {"metadata_json"},
        )
        self._log_event(
            "runtime_attached",
            {
                "match_id": match_id,
                "bot_id": bot_id,
                "instance_serial": serial,
                "instance_label": instance_label,
                "vendor": vendor,
            },
            entity_type="match",
            entity_id=match_id,
            match_id=match_id,
            match_context_version=int(match_row["match_context_version"]),
        )
        return {"ok": True, "attachment": self._load_attachment_for_bot(match_id, bot_id)}

    def detach_runtime_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        match_id = payload["match_id"]
        bot_id = payload["bot_id"]
        match_row = self._load_match(match_id)
        if not match_row:
            return {"ok": False, "error": f"Unknown match_id {match_id}"}
        attachment = self._load_attachment_for_bot(match_id, bot_id)
        if not attachment:
            return {"ok": True, "detached": False}
        self._stop_bot_process(bot_id)
        self._delete_attachment(match_id, bot_id)
        self._upsert_runtime_status(
            {
                "bot_id": bot_id,
                "match_id": None,
                "match_context_version": 0,
                "process_state": BotProcessState.INACTIVE,
                "workflow_state": BotWorkflowState.NOT_READY,
                "selected_brawler": None,
                "last_heartbeat_at": None,
                "last_error_code": None,
                "last_error_reason": None,
                "responsive": 0,
                "active_pid": None,
                "command_id": None,
                "extras_json": {},
            }
        )
        self._log_event(
            "runtime_detached",
            {
                "match_id": match_id,
                "bot_id": bot_id,
                "instance_serial": attachment["instance_serial"],
            },
            entity_type="match",
            entity_id=match_id,
            match_id=match_id,
            match_context_version=int(match_row["match_context_version"]),
        )
        return {"ok": True, "detached": True}

    def detach_match_runtime(self, payload: dict[str, Any]) -> dict[str, Any]:
        match_id = payload["match_id"]
        attachments = self._load_match_attachments(match_id)
        results = []
        for bot_id in list(attachments):
            results.append(self.detach_runtime_instance({"match_id": match_id, "bot_id": bot_id}))
        return {"ok": True, "results": results}

    def _upsert_pick_assignment(self, match_id: str, version: int, team_id: str, bot_id: str, pick_package: dict[str, Any]) -> None:
        brawler = str(pick_package.get("brawler") or "")
        self.repos.upsert(
            "pick_assignments",
            {
                "assignment_id": f"pick_{uuid4().hex[:10]}",
                "match_id": match_id,
                "match_context_version": version,
                "team_id": team_id,
                "bot_id": bot_id,
                "brawler": brawler,
                "state": PickLifecycleState.ASSIGNED,
                "issued_at": now_iso(),
                "started_at": None,
                "confirmed_at": None,
                "pick_package_json": pick_package,
                "loadout_state": LoadoutLifecycleState.APPLYING if pick_package.get("loadout") else LoadoutLifecycleState.NOT_REQUESTED,
                "loadout_result_json": {},
                "failure_code": None,
                "failure_reason": None,
            },
            {"pick_package_json", "loadout_result_json"},
        )
        runtime_row = self.repos.fetch_one("SELECT * FROM bot_runtime_status WHERE bot_id = ?", (bot_id,)) or {"bot_id": bot_id}
        extras = row_json(runtime_row, "extras_json", {}) if "extras_json" in runtime_row else {}
        self.repos.upsert(
            "bot_runtime_status",
            {
                "bot_id": bot_id,
                "match_id": match_id,
                "match_context_version": version,
                "process_state": runtime_row.get("process_state", BotProcessState.INACTIVE),
                "workflow_state": BotWorkflowState.SELECTING_BRAWLER,
                "selected_brawler": brawler,
                "last_heartbeat_at": runtime_row.get("last_heartbeat_at"),
                "last_error_code": None,
                "last_error_reason": None,
                "responsive": int(runtime_row.get("responsive", 0)),
                "active_pid": runtime_row.get("active_pid"),
                "command_id": runtime_row.get("command_id"),
                "extras_json": extras,
            },
            {"extras_json"},
        )

    def regenerate_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        match_id = payload["match_id"]
        if not payload.get("skip_context_bump"):
            bump = self.bump_match_context(match_id, payload.get("reason", "draft_regenerated"))
            if not bump.get("ok"):
                return bump
        match_row = self._load_match(match_id)
        if not match_row:
            return {"ok": False, "error": f"Unknown match_id {match_id}"}
        version = int(match_row["match_context_version"])
        command_key = payload.get("idempotency_key")
        if command_key:
            existing = self.repos.fetch_one("SELECT * FROM command_executions WHERE idempotency_key = ?", (command_key,))
            if existing:
                return {"ok": True, "command_id": existing["command_id"], "reused": True}
        else:
            command_key = f"regenerate_draft:{uuid4().hex}"

        seed = int(payload.get("seed") or int(datetime.now(UTC).timestamp()))
        draft_result = self.draft_builder.build(
            mode=(match_row.get("mode") or "brawlball"),
            map_name=(match_row.get("map_name") or "Unknown map"),
            seed=seed,
            last_comp_signatures=self._last_draft_signatures,
        )
        team_a_packages = [to_plain_dict(item) for item in draft_result.team_a_packages]
        team_b_packages = [to_plain_dict(item) for item in draft_result.team_b_packages]
        team_a = [item["brawler"] for item in team_a_packages]
        team_b = [item["brawler"] for item in team_b_packages]
        self._last_draft_signatures.update({"|".join(sorted(team_a)), "|".join(sorted(team_b))})
        draft_id = f"draft_{uuid4().hex[:8]}"
        generated_at = now_iso()
        self.repos.upsert(
            "draft_plans",
            {
                "draft_id": draft_id,
                "match_id": match_id,
                "match_context_version": version,
                "mode": match_row.get("mode") or "brawlball",
                "map_name": match_row.get("map_name") or "Unknown map",
                "team_a_final_json": team_a,
                "team_b_final_json": team_b,
                "team_a_packages_json": team_a_packages,
                "team_b_packages_json": team_b_packages,
                "meta_snapshot_json": to_plain_dict(draft_result.meta_snapshot),
                "source_provider": self.draft_builder.provider.provider_name,
                "seed": seed,
                "generated_at": generated_at,
            },
            {"team_a_final_json", "team_b_final_json", "team_a_packages_json", "team_b_packages_json", "meta_snapshot_json"},
        )
        command_id = f"cmd_{uuid4().hex[:10]}"
        self.repos.upsert(
            "command_executions",
            {
                "command_id": command_id,
                "idempotency_key": command_key,
                "command_type": "regenerate_draft",
                "target_bot_id": None,
                "match_id": match_id,
                "match_context_version": version,
                "payload_json": {"seed": seed, "draft_id": draft_id},
                "state": CommandLifecycleState.COMPLETED,
                "issued_at": generated_at,
                "accepted_at": generated_at,
                "completed_at": generated_at,
                "failure_code": None,
                "failure_reason": None,
            },
            {"payload_json"},
        )
        teams = {row["team_id"]: row for row in self._load_teams()}
        team_a_ids = list(teams.get(match_row["team_a_id"], {}).get("bot_ids", []))
        team_b_ids = list(teams.get(match_row["team_b_id"], {}).get("bot_ids", []))
        for bot_id, pick_package in zip(team_a_ids, team_a_packages, strict=False):
            self._upsert_pick_assignment(match_id, version, match_row["team_a_id"], bot_id, pick_package)
        for bot_id, pick_package in zip(team_b_ids, team_b_packages, strict=False):
            self._upsert_pick_assignment(match_id, version, match_row["team_b_id"], bot_id, pick_package)
        self.repos.replace_blockers(match_id, version, [])
        self.repos.upsert("matches", {**match_row, "status": MatchStatus.READY_CHECK, "start_time": None, "end_time": None})
        self._log_event(
            "draft_regenerated",
            {
                "draft_id": draft_id,
                "team_a": team_a,
                "team_b": team_b,
                "matched_event": draft_result.meta_snapshot.raw_source_debug.get("event_debug"),
                "meta_source": draft_result.meta_snapshot.source,
                "meta_trophy_range": draft_result.meta_snapshot.trophy_range,
                "meta_confidence": draft_result.meta_snapshot.confidence,
                "meta_debug": draft_result.meta_snapshot.raw_source_debug,
            },
            entity_type="match",
            entity_id=match_id,
            match_id=match_id,
            match_context_version=version,
            error_code=(
                BRAWLIFY_FETCH_FAILED
                if draft_result.meta_snapshot.source == StaticMetaProvider.provider_name
                and draft_result.meta_snapshot.raw_source_debug.get("primary_source") == BrawlifyEventsProvider.provider_name
                else None
            ),
        )
        return {
            "ok": True,
            "command_id": command_id,
            "draft_id": draft_id,
            "team_a": team_a,
            "team_b": team_b,
            "team_a_packages": team_a_packages,
            "team_b_packages": team_b_packages,
            "meta_source": draft_result.meta_snapshot.source,
        }

    def record_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._is_stale_runtime_payload(payload):
            return {"ok": False, "error": STALE_RUNTIME_PAYLOAD}
        bot_id = payload["bot_id"]
        status = self.repos.fetch_one("SELECT * FROM bot_runtime_status WHERE bot_id = ?", (bot_id,)) or {}
        self.repos.upsert(
            "bot_runtime_status",
            {
                "bot_id": bot_id,
                "match_id": payload.get("match_id", status.get("match_id")),
                "match_context_version": int(payload.get("match_context_version", status.get("match_context_version", 0))),
                "process_state": payload.get("process_state", status.get("process_state", BotProcessState.ACTIVE)),
                "workflow_state": payload.get("workflow_state", status.get("workflow_state", BotWorkflowState.NOT_READY)),
                "selected_brawler": payload.get("selected_brawler", status.get("selected_brawler")),
                "last_heartbeat_at": payload.get("timestamp", now_iso()),
                "last_error_code": status.get("last_error_code"),
                "last_error_reason": status.get("last_error_reason"),
                "responsive": 1,
                "active_pid": payload.get("active_pid", status.get("active_pid")),
                "command_id": payload.get("command_id", status.get("command_id")),
                "extras_json": payload.get("extras", row_json(status, "extras_json", {})),
            },
            {"extras_json"},
        )
        return {"ok": True}

    def record_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.record_heartbeat(payload)

    def _update_pick_state(self, payload: dict[str, Any], state: str) -> dict[str, Any]:
        if self._is_stale_runtime_payload(payload):
            return {"ok": False, "error": STALE_RUNTIME_PAYLOAD}
        bot_id = payload["bot_id"]
        match_id = payload["match_id"]
        version = int(payload["match_context_version"])
        assignment = self.repos.fetch_one(
            "SELECT * FROM pick_assignments WHERE match_id = ? AND match_context_version = ? AND bot_id = ?",
            (match_id, version, bot_id),
        )
        if not assignment:
            self._log_event(
                "stale_context_confirmation",
                payload,
                entity_type="pick_assignment",
                entity_id=bot_id,
                match_id=match_id,
                match_context_version=version,
                error_code=STALE_CONTEXT_CONFIRMATION,
            )
            return {"ok": False, "error": STALE_CONTEXT_CONFIRMATION}
        updates = {**assignment, "state": state}
        timestamp = payload.get("timestamp", now_iso())
        updates["pick_package_json"] = payload.get("pick_package") if payload.get("pick_package") is not None else row_json(assignment, "pick_package_json", {})
        loadout_state = payload.get("loadout_state")
        loadout_result = payload.get("loadout_result")
        updates["loadout_result_json"] = loadout_result if loadout_result is not None else row_json(assignment, "loadout_result_json", {})
        if loadout_state:
            updates["loadout_state"] = loadout_state
        elif state == PickLifecycleState.IN_PROGRESS and pick_requires_loadout({"pick_package": row_json(assignment, "pick_package_json", {})}):
            updates["loadout_state"] = LoadoutLifecycleState.APPLYING
        if state == PickLifecycleState.IN_PROGRESS:
            updates["started_at"] = timestamp
        elif state == PickLifecycleState.CONFIRMED:
            updates["confirmed_at"] = timestamp
        elif state == PickLifecycleState.FAILED:
            updates["failure_code"] = payload.get("failure_code") or (
                loadout_result.get("error_code") if isinstance(loadout_result, dict) else None
            ) or BRAWLER_PICK_FAILED
            updates["failure_reason"] = payload.get("failure_reason", "")
            updates["loadout_state"] = loadout_state or LoadoutLifecycleState.FAILED
        self.repos.upsert("pick_assignments", updates, {"pick_package_json", "loadout_result_json"})
        runtime = self.repos.fetch_one("SELECT * FROM bot_runtime_status WHERE bot_id = ?", (bot_id,)) or {}
        workflow_state = BotWorkflowState.BRAWLER_SELECTED if state == PickLifecycleState.CONFIRMED else BotWorkflowState.SELECTING_BRAWLER
        if state == PickLifecycleState.FAILED:
            workflow_state = BotWorkflowState.NOT_READY
        self.repos.upsert(
            "bot_runtime_status",
            {
                "bot_id": bot_id,
                "match_id": match_id,
                "match_context_version": version,
                "process_state": runtime.get("process_state", BotProcessState.ACTIVE),
                "workflow_state": workflow_state,
                "selected_brawler": payload.get("brawler", runtime.get("selected_brawler")),
                "last_heartbeat_at": runtime.get("last_heartbeat_at", timestamp),
                "last_error_code": updates.get("failure_code") if state == PickLifecycleState.FAILED else None,
                "last_error_reason": updates.get("failure_reason") if state == PickLifecycleState.FAILED else None,
                "responsive": int(runtime.get("responsive", 1)),
                "active_pid": runtime.get("active_pid"),
                "command_id": payload.get("command_id", runtime.get("command_id")),
                "extras_json": row_json(runtime, "extras_json", {}),
            },
            {"extras_json"},
        )
        if payload.get("command_id"):
            self.update_command(
                {
                    "command_id": payload["command_id"],
                    "state": (
                        CommandLifecycleState.COMPLETED
                        if state == PickLifecycleState.CONFIRMED
                        else CommandLifecycleState.FAILED
                        if state == PickLifecycleState.FAILED
                        else CommandLifecycleState.ACCEPTED
                    ),
                    "failure_code": updates.get("failure_code"),
                    "failure_reason": updates.get("failure_reason"),
                }
            )
        self._log_event(
            f"pick_{state}",
            payload,
            entity_type="pick_assignment",
            entity_id=assignment["assignment_id"],
            match_id=match_id,
            match_context_version=version,
            error_code=(
                updates.get("failure_code")
                or LOADOUT_VERIFIED_PARTIAL
                if state == PickLifecycleState.CONFIRMED and loadout_warning_state(
                    {
                        "pick_package": row_json(updates, "pick_package_json", {}),
                        "loadout_state": updates.get("loadout_state"),
                        "loadout_result": row_json(updates, "loadout_result_json", {}),
                    }
                )
                else updates.get("failure_code")
            ),
        )
        return {"ok": True}

    def record_pick_started(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._update_pick_state(payload, PickLifecycleState.IN_PROGRESS)

    def record_pick_confirmed(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._update_pick_state(payload, PickLifecycleState.CONFIRMED)

    def record_pick_failed(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._update_pick_state(payload, PickLifecycleState.FAILED)

    def record_error(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._is_stale_runtime_payload(payload):
            return {"ok": False, "error": STALE_RUNTIME_PAYLOAD}
        bot_id = payload.get("bot_id")
        match_id = payload.get("match_id")
        version = int(payload.get("match_context_version", 0))
        status = self.repos.fetch_one("SELECT * FROM bot_runtime_status WHERE bot_id = ?", (bot_id,)) or {}
        self.repos.upsert(
            "bot_runtime_status",
            {
                "bot_id": bot_id,
                "match_id": match_id or status.get("match_id"),
                "match_context_version": version or int(status.get("match_context_version", 0)),
                "process_state": BotProcessState.ERROR,
                "workflow_state": status.get("workflow_state", BotWorkflowState.NOT_READY),
                "selected_brawler": status.get("selected_brawler"),
                "last_heartbeat_at": status.get("last_heartbeat_at", now_iso()),
                "last_error_code": payload.get("error_code"),
                "last_error_reason": payload.get("error_reason"),
                "responsive": 0,
                "active_pid": status.get("active_pid"),
                "command_id": payload.get("command_id", status.get("command_id")),
                "extras_json": row_json(status, "extras_json", {}),
            },
            {"extras_json"},
        )
        if payload.get("command_id"):
            self.update_command(
                {
                    "command_id": payload["command_id"],
                    "state": CommandLifecycleState.FAILED,
                    "failure_code": payload.get("error_code"),
                    "failure_reason": payload.get("error_reason"),
                }
            )
        self._log_event(
            "runtime_error",
            payload,
            entity_type="bot",
            entity_id=bot_id,
            match_id=match_id,
            match_context_version=version,
            error_code=payload.get("error_code"),
        )
        return {"ok": True}

    def update_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = self.repos.fetch_one("SELECT * FROM command_executions WHERE command_id = ?", (payload["command_id"],))
        if not row:
            return {"ok": False, "error": "Unknown command_id"}
        state = payload["state"]
        updated = {**row, "state": state}
        timestamp = payload.get("timestamp", now_iso())
        if state == CommandLifecycleState.ACCEPTED:
            updated["accepted_at"] = timestamp
        if state == CommandLifecycleState.COMPLETED:
            updated["accepted_at"] = updated.get("accepted_at") or timestamp
            updated["completed_at"] = timestamp
        if state == CommandLifecycleState.FAILED:
            updated["failure_code"] = payload.get("failure_code")
            updated["failure_reason"] = payload.get("failure_reason")
        self.repos.upsert(
            "command_executions",
            {**updated, "payload_json": row_json(updated, "payload_json", {})},
            {"payload_json"},
        )
        self._log_event(
            "command_state_updated",
            {
                "command_id": row["command_id"],
                "command_type": row["command_type"],
                "target_bot_id": row.get("target_bot_id"),
                "state": state,
                "failure_code": updated.get("failure_code"),
                "failure_reason": updated.get("failure_reason"),
            },
            entity_type="command",
            entity_id=row["command_id"],
            match_id=row.get("match_id"),
            match_context_version=int(row.get("match_context_version", 0) or 0),
            error_code=updated.get("failure_code"),
        )
        return {"ok": True}

    def next_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        bot_id = payload["bot_id"]
        match_id = payload.get("match_id")
        version = int(payload.get("match_context_version", 0) or 0)
        rows = self.repos.fetch_all(
            """
            SELECT * FROM command_executions
            WHERE target_bot_id = ?
              AND state IN (?, ?)
            ORDER BY issued_at ASC
            """,
            (
                bot_id,
                CommandLifecycleState.ISSUED,
                CommandLifecycleState.ACCEPTED,
            ),
        )
        for row in rows:
            if match_id and row.get("match_id") and row["match_id"] != match_id:
                continue
            if version and int(row.get("match_context_version", 0) or 0) not in {0, version}:
                continue
            row["payload"] = row_json(row, "payload_json", {})
            return {"ok": True, "command": row}
        return {"ok": True, "command": None}

    def post_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.repos.upsert(
            "communication_messages",
            {
                "message_id": payload.get("message_id") or f"msg_{uuid4().hex[:10]}",
                "timestamp": payload.get("timestamp", now_iso()),
                "match_id": payload["match_id"],
                "match_context_version": int(payload["match_context_version"]),
                "team_id": payload["team_id"],
                "from_bot_id": payload["from_bot_id"],
                "type": payload["type"],
                "signal": payload["signal"],
                "payload_json": payload.get("payload", {}),
                "urgency": payload.get("urgency", "normal"),
                "ttl_ms": int(payload.get("ttl_ms", 5000)),
            },
            {"payload_json"},
        )
        return {"ok": True}

    def apply_override(self, payload: dict[str, Any]) -> dict[str, Any]:
        override_id = payload.get("override_id") or f"override_{uuid4().hex[:8]}"
        existing = self.repos.fetch_one("SELECT * FROM manual_overrides WHERE override_id = ?", (override_id,))
        if existing:
            return {"ok": True, "override_id": override_id, "reused": True}
        self.repos.upsert(
            "manual_overrides",
            {
                "override_id": override_id,
                "actor": payload["actor"],
                "timestamp": payload.get("timestamp", now_iso()),
                "reason": payload["reason"],
                "target_entity": payload["target_entity"],
                "effect": payload["effect"],
            },
        )
        if payload["effect"] == "set_match_winner":
            target = payload["target_entity"]
            match_id, winner_team_id = target.split(":", 1)
            match_row = self._load_match(match_id)
            if match_row:
                self.repos.upsert(
                    "matches",
                    {**match_row, "winner_team_id": winner_team_id, "status": MatchStatus.FINISHED, "end_time": now_iso()},
                )
                self.build_report_for_match(match_id)
        self._log_event(
            "manual_override_applied",
            payload,
            entity_type="override",
            entity_id=override_id,
        )
        return {"ok": True, "override_id": override_id}

    def _issue_command(self, command_type: str, payload: dict[str, Any], target_bot_id: str | None = None) -> dict[str, Any]:
        idempotency_key = payload.get("idempotency_key")
        if idempotency_key:
            existing = self.repos.fetch_one("SELECT * FROM command_executions WHERE idempotency_key = ?", (idempotency_key,))
            if existing:
                return {"ok": True, "command_id": existing["command_id"], "reused": True}
        else:
            idempotency_key = f"{command_type}:{uuid4().hex}"
        match_row = self._load_current_match()
        version = int(match_row["match_context_version"]) if match_row else 0
        command_id = f"cmd_{uuid4().hex[:10]}"
        self.repos.upsert(
            "command_executions",
            {
                "command_id": command_id,
                "idempotency_key": idempotency_key,
                "command_type": command_type,
                "target_bot_id": target_bot_id,
                "match_id": payload.get("match_id"),
                "match_context_version": int(payload.get("match_context_version", version)),
                "payload_json": payload,
                "state": CommandLifecycleState.ISSUED,
                "issued_at": now_iso(),
                "accepted_at": None,
                "completed_at": None,
                "failure_code": None,
                "failure_reason": None,
            },
            {"payload_json"},
        )
        self._log_event(
            "command_issued",
            {
                "command_id": command_id,
                "command_type": command_type,
                "target_bot_id": target_bot_id,
                "payload": payload,
            },
            entity_type="command",
            entity_id=command_id,
            match_id=payload.get("match_id"),
            match_context_version=int(payload.get("match_context_version", version)),
        )
        return {"ok": True, "command_id": command_id, "reused": False}

    def launch_bot(self, payload: dict[str, Any]) -> dict[str, Any]:
        bot_id = payload["bot_id"]
        match_row = self._load_match(payload["match_id"])
        if not match_row:
            self._log_event(
                "bot_launch_failed",
                {"bot_id": bot_id, "error": "Unknown match for bot launch."},
                entity_type="bot",
                entity_id=bot_id,
                error_code=COMMAND_TARGET_MISSING,
            )
            return {"ok": False, "error": "Unknown match for bot launch."}
        assignment = self.repos.fetch_one(
            "SELECT * FROM pick_assignments WHERE match_id = ? AND match_context_version = ? AND bot_id = ?",
            (payload["match_id"], int(match_row["match_context_version"]), bot_id),
        )
        if not assignment:
            self._log_event(
                "bot_launch_failed",
                {"bot_id": bot_id, "error": COMMAND_TARGET_MISSING},
                entity_type="bot",
                entity_id=bot_id,
                match_id=payload["match_id"],
                match_context_version=int(match_row["match_context_version"]),
                error_code=COMMAND_TARGET_MISSING,
            )
            return {"ok": False, "error": COMMAND_TARGET_MISSING}
        assignment["pick_package"] = row_json(assignment, "pick_package_json", {})
        assignment["loadout_result"] = row_json(assignment, "loadout_result_json", {})
        bot = self.repos.fetch_one("SELECT * FROM bots WHERE bot_id = ?", (bot_id,))
        if not bot:
            self._log_event(
                "bot_launch_failed",
                {"bot_id": bot_id, "error": "Unknown bot."},
                entity_type="bot",
                entity_id=bot_id,
                match_id=payload["match_id"],
                match_context_version=int(match_row["match_context_version"]),
                error_code=COMMAND_TARGET_MISSING,
            )
            return {"ok": False, "error": "Unknown bot."}
        attachment = self._load_attachment_for_bot(payload["match_id"], bot_id)
        if not attachment:
            self._log_event(
                "bot_launch_failed",
                {"bot_id": bot_id, "error": BOT_NOT_ATTACHED_TO_ACTIVE_MATCH},
                entity_type="bot",
                entity_id=bot_id,
                match_id=payload["match_id"],
                match_context_version=int(match_row["match_context_version"]),
                error_code=BOT_NOT_ATTACHED_TO_ACTIVE_MATCH,
            )
            return {"ok": False, "error": BOT_NOT_ATTACHED_TO_ACTIVE_MATCH}

        command_result = self._issue_command(
            "assign_pick",
            {
                **payload,
                "brawler": assignment["brawler"],
                "pick_package": assignment["pick_package"],
                "team_id": bot.get("assigned_team_id") or "",
            },
            target_bot_id=bot_id,
        )
        command_id = command_result["command_id"]

        self._stop_bot_process(bot_id)
        assignment_payload = {key: value for key, value in assignment.items() if key not in {"pick_package", "loadout_result"}}
        self.repos.upsert(
            "pick_assignments",
            {
                **assignment_payload,
                "state": PickLifecycleState.ASSIGNED,
                "issued_at": now_iso(),
                "started_at": None,
                "confirmed_at": None,
                "pick_package_json": assignment.get("pick_package") or {},
                "loadout_state": (
                    LoadoutLifecycleState.APPLYING
                    if (assignment.get("pick_package") or {}).get("loadout")
                    else LoadoutLifecycleState.NOT_REQUESTED
                ),
                "loadout_result_json": {},
                "failure_code": None,
                "failure_reason": None,
            },
            {"pick_package_json", "loadout_result_json"},
        )

        args = [
            sys.executable,
            "-u",
            str(RUNTIME_SCRIPT),
            "--skip-gui",
            "--assigned-brawler",
            assignment["brawler"],
            "--assigned-pick-package-json",
            json.dumps(assignment.get("pick_package") or {}, ensure_ascii=False),
            "--coordinator-url",
            f"http://{self.host}:{self.port}",
            "--bot-id",
            bot_id,
            "--team-id",
            bot.get("assigned_team_id") or "",
            "--instance-id",
            attachment["instance_serial"],
            "--instance-serial",
            attachment["instance_serial"],
            "--match-id",
            payload["match_id"],
            "--match-context-version",
            str(match_row["match_context_version"]),
            "--platform",
            bot.get("platform", "nulls"),
            "--command-id",
            command_id,
        ]
        if bot_id == self._friendly_host_bot_id(match_row):
            args.append("--friendly-host")
        try:
            logs_dir = DATA_DIR / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_handle = (logs_dir / f"{bot_id}.log").open("w", encoding="utf-8")
            process = subprocess.Popen(
                args,
                cwd=BASE_DIR,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self._bot_log_handles[bot_id] = log_handle
        except Exception as exc:
            self.update_command(
                {
                    "command_id": command_id,
                    "state": CommandLifecycleState.FAILED,
                    "failure_code": WORKER_LAUNCH_FAILED,
                    "failure_reason": str(exc),
                }
            )
            self._log_event(
                "bot_launch_failed",
                {"bot_id": bot_id, "error": str(exc)},
                entity_type="bot",
                entity_id=bot_id,
                match_id=payload["match_id"],
                match_context_version=int(match_row["match_context_version"]),
                error_code=WORKER_LAUNCH_FAILED,
            )
            return {"ok": False, "error": str(exc)}
        self._bot_processes[bot_id] = process
        status = self.repos.fetch_one("SELECT * FROM bot_runtime_status WHERE bot_id = ?", (bot_id,)) or {}
        self._upsert_runtime_status(
            {
                "bot_id": bot_id,
                "match_id": payload["match_id"],
                "match_context_version": int(match_row["match_context_version"]),
                "process_state": BotProcessState.LAUNCHING,
                "workflow_state": BotWorkflowState.SELECTING_BRAWLER,
                "selected_brawler": assignment["brawler"],
                "last_heartbeat_at": status.get("last_heartbeat_at"),
                "last_error_code": None,
                "last_error_reason": None,
                "responsive": 0,
                "active_pid": process.pid,
                "command_id": command_id,
                "extras_json": row_json(status, "extras_json", {}),
            }
        )
        self._log_event(
            "bot_launch_accepted",
            {
                "bot_id": bot_id,
                "command_id": command_id,
                "pid": process.pid,
                "instance_serial": attachment["instance_serial"],
                "instance_label": attachment["instance_label"],
            },
            entity_type="bot",
            entity_id=bot_id,
            match_id=payload["match_id"],
            match_context_version=int(match_row["match_context_version"]),
        )
        return {"ok": True, "command_id": command_id, "pid": process.pid}

    def launch_match_bots(self, payload: dict[str, Any]) -> dict[str, Any]:
        match_id = payload["match_id"]
        match_row = self._load_match(match_id)
        if not match_row:
            return {"ok": False, "error": "Unknown match."}
        attachments = self._load_match_attachments(match_id)
        teams = {row["team_id"]: row for row in self._load_teams()}
        bot_ids = list(teams.get(match_row["team_a_id"], {}).get("bot_ids", [])) + list(
            teams.get(match_row["team_b_id"], {}).get("bot_ids", [])
        )
        results = []
        for bot_id in bot_ids:
            if bot_id not in attachments:
                results.append({"ok": False, "bot_id": bot_id, "error": BOT_NOT_ATTACHED_TO_ACTIVE_MATCH})
                continue
            result = self.launch_bot({"bot_id": bot_id, "match_id": match_id})
            result["bot_id"] = bot_id
            results.append(result)
        return {"ok": True, "results": results}

    def auto_register_and_build_teams(self, payload: dict[str, Any]) -> dict[str, Any]:
        provided_instances = payload.get("instances")
        if isinstance(provided_instances, list):
            instances = [item for item in provided_instances if isinstance(item, dict) and item.get("serial")]
        else:
            instances = detect_instances()
        requested_teams = max(1, min(int(payload.get("team_count", 2)), 4))
        available_teams = min(requested_teams, len(instances) // 3)
        if available_teams <= 0:
            return {"ok": False, "error": "Need at least 3 detected instances to build one team."}

        registered: list[str] = []
        teams: list[str] = []
        team_names = payload.get("team_names") or ["Team Alpha", "Team Bravo", "Team Charlie", "Team Delta"]
        team_colors = payload.get("team_colors") or ["#d2452d", "#2d7dd2", "#2dbd7f", "#c78f1d"]
        team_color_by_tag = {"FUT": "#d2452d", "ZL": "#2d7dd2", "NX": "#2dbd7f", "SK": "#c78f1d"}
        bot_id_to_instance: dict[str, dict[str, Any]] = {}

        for item in instances:
            serial = str(item["serial"])
            bot_id = serial.replace(":", "_").replace(".", "_")
            bot_id_to_instance[bot_id] = item
            self.upsert_bot(
                {
                    "bot_id": bot_id,
                    "instance_id": serial,
                    "display_name": str(item.get("parsed_player_name") or item.get("display_label") or serial),
                    "platform": payload.get("platform", "nulls"),
                    "metadata": item,
                }
            )
            registered.append(bot_id)

        tagged_groups: dict[str, list[str]] = {tag: [] for tag in KNOWN_TEAM_TAGS}
        unassigned: list[str] = []
        for bot_id in registered:
            instance = bot_id_to_instance.get(bot_id, {})
            team_tag = str(instance.get("parsed_team_tag") or "").upper()
            if team_tag in tagged_groups:
                tagged_groups[team_tag].append(bot_id)
            else:
                unassigned.append(bot_id)

        built_groups: list[tuple[str | None, list[str]]] = []
        for team_tag in KNOWN_TEAM_TAGS:
            members = tagged_groups.get(team_tag, [])
            if len(members) >= 3 and len(built_groups) < available_teams:
                built_groups.append((team_tag, members[:3]))

        remaining_pool = list(unassigned)
        for team_tag in KNOWN_TEAM_TAGS:
            members = tagged_groups.get(team_tag, [])
            if len(members) < 3:
                remaining_pool.extend(members)

        while len(built_groups) < available_teams and len(remaining_pool) >= 3:
            built_groups.append((None, remaining_pool[:3]))
            remaining_pool = remaining_pool[3:]

        for team_index, (team_tag, bot_ids) in enumerate(built_groups):
            team_id = f"team_{team_index + 1:02d}"
            self.create_or_update_team(
                {
                    "team_id": team_id,
                    "name": team_tag or (team_names[team_index] if team_index < len(team_names) else team_id),
                    "color": (team_color_by_tag.get(team_tag) if team_tag else None) or (team_colors[team_index] if team_index < len(team_colors) else "#d2452d"),
                    "bot_ids": bot_ids,
                }
            )
            teams.append(team_id)

        self._log_event(
            "instances_registered_and_teams_built",
            {"registered_bot_ids": registered, "team_ids": teams, "tagged_groups": tagged_groups},
            entity_type="system",
            entity_id="auto_team_builder",
        )
        return {"ok": True, "registered_bot_ids": registered, "team_ids": teams, "instances": instances}

    def create_quick_match(self, payload: dict[str, Any]) -> dict[str, Any]:
        dashboard_teams = self._load_teams()
        provided_team_ids = [team_id for team_id in payload.get("team_ids", []) if team_id]
        team_ids = provided_team_ids or [team["team_id"] for team in dashboard_teams[:2]]
        if len(team_ids) < 2:
            return {"ok": False, "error": "Quick match needs 2 teams."}
        tournament_id = payload.get("tournament_id") or f"quickmatch_{uuid4().hex[:8]}"
        match_id = payload.get("match_id") or f"match_{uuid4().hex[:8]}"
        created_at = now_iso()
        self.repos.upsert(
            "tournaments",
            {
                "tournament_id": tournament_id,
                "name": payload.get("name") or "Quick 3v3",
                "status": TournamentState.DRAFTING,
                "stage": MatchStage.EXHIBITION,
                "team_ids_json": team_ids[:2],
                "current_match_id": match_id,
                "winner_team_id": None,
                "created_at": created_at,
                "finished_at": None,
            },
            {"team_ids_json"},
        )
        self.repos.upsert(
            "matches",
            {
                "match_id": match_id,
                "tournament_id": tournament_id,
                "stage": MatchStage.EXHIBITION,
                "mode": payload.get("mode"),
                "map_name": payload.get("map_name"),
                "best_of": int(payload.get("best_of", 1)),
                "team_a_id": team_ids[0],
                "team_b_id": team_ids[1],
                "match_context_version": 1,
                "status": MatchStatus.DRAFTING,
                "start_time": None,
                "end_time": None,
                "winner_team_id": None,
            },
        )
        created_match = self._load_match(match_id)
        if created_match:
            self._reset_runtime_for_context(created_match, 1)
        self._log_event(
            "quick_match_created",
            {"tournament_id": tournament_id, "match_id": match_id, "team_ids": team_ids[:2]},
            entity_type="match",
            entity_id=match_id,
            match_id=match_id,
            match_context_version=1,
        )
        return {"ok": True, "tournament_id": tournament_id, "match_id": match_id}

    def prepare_live_match(self, payload: dict[str, Any]) -> dict[str, Any]:
        teams = self._load_teams()
        if len(teams) < 2:
            register_result = self.auto_register_and_build_teams({"team_count": 2, "platform": payload.get("platform", "nulls")})
            if not register_result.get("ok"):
                return register_result
            teams = self._load_teams()
        team_ids = [team["team_id"] for team in teams[:2]]
        current_match = self._load_current_match()
        if current_match and current_match.get("status") not in {MatchStatus.FINISHED, MatchStatus.FAILED}:
            match_id = current_match["match_id"]
        else:
            created = self.create_quick_match({"team_ids": team_ids, "name": payload.get("name") or "Quick 3v3"})
            if not created.get("ok"):
                return created
            match_id = created["match_id"]
        configured = self.update_match_config(
            {
                "match_id": match_id,
                "mode": payload.get("mode") or "brawlball",
                "map_name": payload.get("map_name") or "Friendly Arena",
                "reason": payload.get("reason", "prepare_live_match"),
            }
        )
        return {"ok": True, "match_id": match_id, "configured": configured}

    def start_match_flow(self, payload: dict[str, Any]) -> dict[str, Any]:
        match_id = payload["match_id"]
        match_row = self._load_match(match_id)
        if not match_row:
            return {"ok": False, "error": "Unknown match."}
        if match_row["status"] in {MatchStatus.STARTING, MatchStatus.IN_MATCH, MatchStatus.FINISHED}:
            return {"ok": True, "match_id": match_id, "status": match_row["status"], "reused": True}
        preflight_result = self.preflight({"match_id": match_id})
        if not preflight_result.get("ok"):
            return preflight_result
        if not preflight_result.get("match_start_allowed"):
            self._set_tournament_status(TournamentState.ERROR_RECOVERY)
            return {
                "ok": False,
                "error": "Match start blocked.",
                "blockers": preflight_result.get("blockers", []),
            }
        updated = self._set_match_status(match_row, MatchStatus.STARTING)
        self._set_tournament_status(TournamentState.MATCH_STARTING)
        self._match_runtime_meta[match_id] = {
            **self._match_runtime_meta.get(match_id, {}),
            "start_requested_at": now_iso(),
            "matchmaking_timeout_logged": False,
            "lobby_timeout_logged": False,
        }
        self._log_event(
            "match_flow_started",
            {"match_id": match_id, "match_context_version": int(updated["match_context_version"])},
            entity_type="match",
            entity_id=match_id,
            match_id=match_id,
            match_context_version=int(updated["match_context_version"]),
        )
        return {"ok": True, "match_id": match_id, "status": MatchStatus.STARTING}

    def run_match_recovery(self, payload: dict[str, Any]) -> dict[str, Any]:
        match_id = payload["match_id"]
        match_row = self._load_match(match_id)
        if not match_row:
            return {"ok": False, "error": "Unknown match."}
        self._refresh_process_states()
        result = self._run_operational_cycle(match_row=match_row)
        refreshed = self._load_match(match_id)
        return {"ok": True, "match": refreshed, "recovery": result}

    def _append_runtime_blocker(
        self,
        match_row: dict[str, Any],
        *,
        code: str,
        message: str,
        suggested_action: str,
        bot_id: str | None = None,
        team_id: str | None = None,
        severity: str = BlockerSeverity.ERROR,
    ) -> None:
        blockers = self._load_match_blockers(match_row["match_id"], int(match_row["match_context_version"]))
        key = (code, bot_id, team_id)
        for blocker in blockers:
            if (blocker["code"], blocker.get("bot_id"), blocker.get("team_id")) == key:
                return
        blockers.append(
            {
                "code": code,
                "severity": severity,
                "message": message,
                "bot_id": bot_id,
                "team_id": team_id,
                "recoverable": True,
                "suggested_action": suggested_action,
            }
        )
        self._replace_blockers(match_row, blockers)

    def _attempt_bot_relaunch(self, match_row: dict[str, Any], bot_id: str, reason: str, error_code: str) -> dict[str, Any]:
        if not self._can_attempt_relaunch(bot_id, reason):
            return {"ok": False, "reason": "limit_reached"}
        recovery = self._mark_recovery_attempt(bot_id, reason)
        self._log_event(
            "bot_relaunch_requested",
            {"bot_id": bot_id, "reason": reason, "attempts": recovery.get("attempts", {})},
            entity_type="bot",
            entity_id=bot_id,
            match_id=match_row["match_id"],
            match_context_version=int(match_row["match_context_version"]),
            error_code=error_code,
        )
        return self.launch_bot({"bot_id": bot_id, "match_id": match_row["match_id"], "reason": reason})

    def _handle_prematch_recovery(
        self,
        match_row: dict[str, Any],
        statuses: dict[str, dict[str, Any]],
        assignments: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        attachments = self._load_match_attachments(match_row["match_id"])
        for bot_id in self._match_bot_ids(match_row):
            if bot_id not in attachments:
                continue
            runtime = statuses.get(bot_id, {})
            assignment = assignments.get(bot_id)
            process_state = runtime.get("process_state")
            if process_state in {BotProcessState.UNRESPONSIVE, BotProcessState.CRASHED, BotProcessState.ERROR}:
                result = self._attempt_bot_relaunch(match_row, bot_id, "runtime_unresponsive", BOT_UNRESPONSIVE)
                actions.append({"bot_id": bot_id, "action": "relaunch_runtime", "result": result})
                continue
            if not assignment:
                continue
            reference_time = parse_iso(assignment.get("started_at") or assignment.get("issued_at"))
            if not reference_time:
                continue
            if assignment.get("state") in {PickLifecycleState.ASSIGNED, PickLifecycleState.IN_PROGRESS} and (
                now - reference_time
            ).total_seconds() >= PICK_CONFIRM_TIMEOUT_SECONDS:
                result = self._attempt_bot_relaunch(match_row, bot_id, "pick_timeout", PICK_CONFIRM_TIMEOUT)
                actions.append({"bot_id": bot_id, "action": "relaunch_pick_timeout", "result": result})
        return actions

    def _handle_match_start_flow(
        self,
        match_row: dict[str, Any],
        statuses: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        match_id = match_row["match_id"]
        version = int(match_row["match_context_version"])
        attachments = self._load_match_attachments(match_id)
        bot_ids = [bot_id for bot_id in self._match_bot_ids(match_row) if bot_id in attachments]
        relevant_statuses = {
            bot_id: statuses.get(bot_id, {})
            for bot_id in bot_ids
            if int(statuses.get(bot_id, {}).get("match_context_version", -1)) == version
        }
        assignments = self._load_pick_assignments(match_id, version)
        relevant = list(relevant_statuses.values())
        workflows = [row.get("workflow_state") for row in relevant]
        blockers = self._load_match_blockers(match_id, version)
        meta = self._match_runtime_meta.setdefault(match_id, {})
        start_requested_at = parse_iso(meta.get("start_requested_at"))
        now = datetime.now(UTC)
        host_bot_id = self._select_host_for_start(match_row, relevant_statuses, assignments)
        if not host_bot_id:
            self._append_runtime_blocker(
                match_row,
                code=HOST_NOT_AVAILABLE,
                message="No viable host bot is available for friendly battle start.",
                suggested_action="Recover Team A bots or relaunch a ready host candidate before starting.",
                team_id=match_row.get("team_a_id"),
            )
            self._set_tournament_status(TournamentState.ERROR_RECOVERY)
            return actions
        host_status = relevant_statuses.get(host_bot_id or "", {})
        host_snapshot = self._friendly_snapshot(host_status)
        start_command = self._load_command(meta.get("start_command_id"))
        if not start_command and host_bot_id:
            start_command = self._find_active_command(
                target_bot_id=host_bot_id,
                match_id=match_id,
                match_context_version=version,
                command_type="start_matchmaking",
            )
            if start_command:
                meta["start_command_id"] = start_command["command_id"]

        if any(row["severity"] == BlockerSeverity.ERROR for row in blockers):
            return actions

        if any(state == BotWorkflowState.IN_MATCH for state in workflows):
            updated = self._set_match_status(match_row, MatchStatus.IN_MATCH, touch_start=True)
            self._set_tournament_status(TournamentState.IN_MATCH)
            self._log_event(
                "match_started_confirmed",
                {"match_id": match_id},
                entity_type="match",
                entity_id=match_id,
                match_id=match_id,
                match_context_version=version,
            )
            return actions

        matchmaking_entered = any(state == BotWorkflowState.MATCHMAKING for state in workflows) or any(
            self._friendly_snapshot(status).get("matchmaking_entered") for status in relevant
        )
        if matchmaking_entered and not meta.get("matchmaking_entered_logged"):
            meta["matchmaking_entered_logged"] = True
            meta["matchmaking_entered_at"] = now_iso()
            self._log_event(
                "matchmaking_entered",
                {"match_id": match_id, "host_bot_id": host_bot_id},
                entity_type="match",
                entity_id=match_id,
                match_id=match_id,
                match_context_version=version,
            )

        if host_bot_id and not start_command:
            command_result = self._issue_command(
                "start_matchmaking",
                {
                    "match_id": match_id,
                    "match_context_version": version,
                    "host_bot_id": host_bot_id,
                    "platform": (self.repos.fetch_one("SELECT * FROM bots WHERE bot_id = ?", (host_bot_id,)) or {}).get("platform", "nulls"),
                },
                target_bot_id=host_bot_id,
            )
            meta["start_command_id"] = command_result["command_id"]
            self._log_event(
                "start_matchmaking_issued",
                {"match_id": match_id, "host_bot_id": host_bot_id, "command_id": command_result["command_id"]},
                entity_type="match",
                entity_id=match_id,
                match_id=match_id,
                match_context_version=version,
            )
            return actions

        if start_command and start_command.get("state") == CommandLifecycleState.FAILED:
            self._append_runtime_blocker(
                match_row,
                code=MATCHMAKING_NOT_ENTERED,
                message=f"Host bot {host_bot_id} failed to enter matchmaking: {start_command.get('failure_reason') or 'unknown error'}.",
                suggested_action="Retry friendly battle start or relaunch the host bot.",
                bot_id=host_bot_id,
            )
            self._set_tournament_status(TournamentState.ERROR_RECOVERY)
            return actions

        if start_requested_at and (now - start_requested_at).total_seconds() >= MATCH_START_TIMEOUT_SECONDS:
            if matchmaking_entered:
                self._append_runtime_blocker(
                    match_row,
                    code=MATCH_START_NOT_CONFIRMED,
                    message="Bots entered matchmaking, but the match did not start in time.",
                    suggested_action="Retry the friendly battle or rebuild the room state before relaunching.",
                )
                if not meta.get("match_start_timeout_logged"):
                    self._set_tournament_status(TournamentState.ERROR_RECOVERY)
                    self._log_event(
                        "match_start_timeout",
                        {"match_id": match_id},
                        entity_type="match",
                        entity_id=match_id,
                        match_id=match_id,
                        match_context_version=version,
                        error_code=MATCH_START_NOT_CONFIRMED,
                    )
                    meta["match_start_timeout_logged"] = True
            else:
                self._append_runtime_blocker(
                    match_row,
                    code=MATCHMAKING_NOT_ENTERED,
                    message="Host bot never entered matchmaking after start command.",
                    suggested_action="Verify the friendly battle lobby and rerun recovery.",
                    bot_id=host_bot_id,
                )
                if not meta.get("matchmaking_timeout_logged"):
                    self._set_tournament_status(TournamentState.ERROR_RECOVERY)
                    self._log_event(
                        "lobby_join_timeout",
                        {"match_id": match_id},
                        entity_type="match",
                        entity_id=match_id,
                        match_id=match_id,
                        match_context_version=version,
                        error_code=MATCHMAKING_NOT_ENTERED,
                    )
                    meta["matchmaking_timeout_logged"] = True
            actions.extend(self._handle_prematch_recovery(match_row, statuses, assignments))
            if actions:
                self._set_match_status(match_row, MatchStatus.READY_CHECK)
        return actions

    def _handle_match_completion(
        self,
        match_row: dict[str, Any],
        statuses: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        version = int(match_row["match_context_version"])
        bot_ids = self._match_bot_ids(match_row)
        relevant = [
            statuses.get(bot_id, {})
            for bot_id in bot_ids
            if int(statuses.get(bot_id, {}).get("match_context_version", -1)) == version
        ]
        workflows = [row.get("workflow_state") for row in relevant]
        if not relevant:
            return {"finished": False}
        if any(state in {BotWorkflowState.IN_MATCH, BotWorkflowState.MATCHMAKING} for state in workflows):
            for row in relevant:
                if row.get("process_state") in {BotProcessState.CRASHED, BotProcessState.UNRESPONSIVE, BotProcessState.ERROR}:
                    self._append_runtime_blocker(
                        match_row,
                        code=BOT_UNRESPONSIVE,
                        message=f"Bot {row['bot_id']} dropped during active match.",
                        suggested_action="Use manual override or replay the match.",
                        bot_id=row["bot_id"],
                    )
                    self._set_tournament_status(TournamentState.ERROR_RECOVERY)
            return {"finished": False}
        if any(state in {BotWorkflowState.POST_MATCH, BotWorkflowState.IN_LOBBY, BotWorkflowState.BRAWLER_SELECTED} for state in workflows):
            updated = self._set_match_status(match_row, MatchStatus.FINISHED, touch_end=True)
            self._set_tournament_status(TournamentState.MATCH_FINISHED)
            report = self.build_report_for_match(updated["match_id"])
            self._log_event(
                "match_finished_runtime",
                {"match_id": updated["match_id"], "report_ok": report.get("ok", False)},
                entity_type="match",
                entity_id=updated["match_id"],
                match_id=updated["match_id"],
                match_context_version=version,
            )
            return {"finished": True, "report": report}
        return {"finished": False}

    def _run_operational_cycle(
        self,
        *,
        match_row: dict[str, Any] | None = None,
        forced: bool = False,
    ) -> dict[str, Any]:
        match_row = match_row or self._load_current_match()
        if not match_row:
            return {"ok": True, "actions": [], "match": None}
        version = int(match_row["match_context_version"])
        statuses = self._load_runtime_statuses()
        assignments = self._load_pick_assignments(match_row["match_id"], version)
        actions: list[dict[str, Any]] = []

        if match_row["status"] in {MatchStatus.DRAFTING, MatchStatus.READY_CHECK, MatchStatus.LOBBY_SETUP, MatchStatus.STARTING}:
            preflight_result = self.preflight({"match_id": match_row["match_id"]})
        else:
            preflight_result = {
                "ok": True,
                "match_start_allowed": True,
                "blockers": self._load_match_blockers(match_row["match_id"], version),
            }
        match_row = self._load_match(match_row["match_id"]) or match_row
        match_status = match_row["status"]
        if match_status in {MatchStatus.DRAFTING, MatchStatus.READY_CHECK, MatchStatus.LOBBY_SETUP}:
            actions.extend(self._handle_prematch_recovery(match_row, statuses, assignments))
            if preflight_result.get("match_start_allowed") and match_status == MatchStatus.READY_CHECK:
                match_row = self._set_match_status(match_row, MatchStatus.LOBBY_SETUP)
                self._set_tournament_status(TournamentState.LOBBY_SETUP)
                self._log_event(
                    "match_ready_for_lobby",
                    {"match_id": match_row["match_id"], "ready_bots": self._current_ready_bots(match_row)},
                    entity_type="match",
                    entity_id=match_row["match_id"],
                    match_id=match_row["match_id"],
                    match_context_version=version,
                )
        elif match_status == MatchStatus.STARTING:
            actions.extend(self._handle_prematch_recovery(match_row, statuses, assignments))
            actions.extend(self._handle_match_start_flow(match_row, statuses))
        if match_row["status"] == MatchStatus.IN_MATCH:
            completion = self._handle_match_completion(match_row, statuses)
            actions.append({"match_completion": completion})
        return {"ok": True, "actions": actions, "match": self._load_match(match_row["match_id"])}

    def preflight(self, payload: dict[str, Any]) -> dict[str, Any]:
        match_id = payload["match_id"]
        match_row = self._load_match(match_id)
        if not match_row:
            return {"ok": False, "error": "Unknown match."}
        self._refresh_process_states()
        teams_lookup = {row["team_id"]: row for row in self._load_teams()}
        teams = [
            teams_lookup.get(match_row["team_a_id"], {"team_id": match_row["team_a_id"], "name": "TBD", "bot_ids": []}),
            teams_lookup.get(match_row["team_b_id"], {"team_id": match_row["team_b_id"], "name": "TBD", "bot_ids": []}),
        ]
        statuses = self._load_runtime_statuses()
        attachments = self._load_match_attachments(match_id)
        assignments = self._load_pick_assignments(match_id, int(match_row["match_context_version"]))
        blockers = derive_match_start_blockers(
            match_context_version=int(match_row["match_context_version"]),
            mode=match_row.get("mode"),
            map_name=match_row.get("map_name"),
            observer_ready=self.observer.healthy,
            teams=teams,
            runtime_statuses=statuses,
            runtime_attachments=attachments,
            pick_assignments=assignments,
            stage_valid=match_row["status"] in {MatchStatus.READY_CHECK, MatchStatus.LOBBY_SETUP, MatchStatus.DRAFTING, MatchStatus.STARTING},
        )
        blocker_payload = [to_plain_dict(item) for item in blockers]
        blocker_payload.extend(self._derive_platform_blockers(match_row, statuses))
        self.repos.replace_blockers(match_id, int(match_row["match_context_version"]), blocker_payload)
        return {
            "ok": True,
            "blockers": blocker_payload,
            "match_start_allowed": len([b for b in blocker_payload if b["severity"] == BlockerSeverity.ERROR]) == 0,
        }

    def build_report_for_match(self, match_id: str) -> dict[str, Any]:
        match_row = self._load_match(match_id)
        if not match_row:
            return {"ok": False, "error": "Unknown match."}
        try:
            draft_row = self._load_latest_draft(match_id, int(match_row["match_context_version"]))
            notes = self.repos.fetch_all(
                "SELECT * FROM observer_notes WHERE match_id = ? AND match_context_version = ? ORDER BY timestamp",
                (match_id, int(match_row["match_context_version"])),
            )
            messages = self.repos.fetch_all(
                "SELECT * FROM communication_messages WHERE match_id = ? AND match_context_version = ? ORDER BY timestamp",
                (match_id, int(match_row["match_context_version"])),
            )
            overrides = self.repos.fetch_all(
                "SELECT * FROM manual_overrides WHERE target_entity LIKE ? ORDER BY timestamp DESC LIMIT 20",
                (f"{match_id}:%",),
            )
            teams_lookup = {row["team_id"]: row for row in self._load_teams()}
            bot_ids = list(teams_lookup.get(match_row["team_a_id"], {}).get("bot_ids", [])) + list(
                teams_lookup.get(match_row["team_b_id"], {}).get("bot_ids", [])
            )
            outputs = self.observer.build_match_outputs(
                match_row=match_row,
                draft_row=draft_row,
                notes=notes,
                messages=messages,
                overrides=overrides,
                bot_ids=bot_ids,
            )
            report: MatchReport = outputs["report"]
            report_dict = to_plain_dict(report)
            self.repos.upsert(
                "match_reports",
                {
                    "match_id": match_id,
                    "tournament_id": match_row["tournament_id"],
                    "match_context_version": int(match_row["match_context_version"]),
                    "report_json": report_dict,
                },
                {"report_json"},
            )
            self.exporter.write_json(self.exporter.reports_dir, match_id, report_dict)
            self.exporter.write_json(self.exporter.highlights_dir, match_id, {"highlights": outputs["highlights"]})
            return {"ok": True, "report": report_dict}
        except Exception as exc:
            self._log_event(
                "report_build_failed",
                {"match_id": match_id, "error": str(exc)},
                entity_type="match",
                entity_id=match_id,
                match_id=match_id,
                match_context_version=int(match_row["match_context_version"]),
                error_code=REPORT_BUILD_FAILED,
            )
            return {"ok": False, "error": str(exc), "error_code": REPORT_BUILD_FAILED}

    def advance_stage(self, payload: dict[str, Any]) -> dict[str, Any]:
        tournament = self._load_current_tournament()
        if not tournament:
            return {"ok": False, "error": "No active tournament."}
        current_stage = tournament["stage"]
        if current_stage == MatchStage.EXHIBITION:
            next_stage = TournamentState.TOURNAMENT_FINISHED
        elif current_stage == MatchStage.SEMIFINAL_1:
            next_stage = MatchStage.SEMIFINAL_2
        elif current_stage == MatchStage.SEMIFINAL_2:
            next_stage = MatchStage.FINAL
        elif current_stage == MatchStage.FINAL:
            next_stage = TournamentState.TOURNAMENT_FINISHED
        else:
            return {"ok": False, "error": "Unknown stage."}

        if next_stage == TournamentState.TOURNAMENT_FINISHED:
            self._persist_tournament(
                tournament,
                status=TournamentState.TOURNAMENT_FINISHED,
                stage=current_stage,
                finished_at=now_iso(),
            )
            return {"ok": True, "stage": TournamentState.TOURNAMENT_FINISHED}

        next_match = self.repos.fetch_one(
            "SELECT * FROM matches WHERE tournament_id = ? AND stage = ?",
            (tournament["tournament_id"], next_stage),
        )
        if not next_match:
            return {"ok": False, "error": "Next bracket match not found."}
        if next_stage == MatchStage.FINAL:
            semifinal_rows = self.repos.fetch_all(
                "SELECT * FROM matches WHERE tournament_id = ? AND stage IN (?, ?)",
                (tournament["tournament_id"], MatchStage.SEMIFINAL_1, MatchStage.SEMIFINAL_2),
            )
            winners = {row["stage"]: row.get("winner_team_id") for row in semifinal_rows}
            next_match = {
                **next_match,
                "team_a_id": winners.get(MatchStage.SEMIFINAL_1, ""),
                "team_b_id": winners.get(MatchStage.SEMIFINAL_2, ""),
            }
        self._persist_tournament(
            tournament,
            status=TournamentState.DRAFTING,
            stage=next_stage,
            current_match_id=next_match["match_id"],
        )
        self.repos.upsert("matches", {**next_match, "status": MatchStatus.DRAFTING})
        self._log_event(
            "tournament_stage_advanced",
            {"tournament_id": tournament["tournament_id"], "stage": next_stage},
            entity_type="tournament",
            entity_id=tournament["tournament_id"],
        )
        return {"ok": True, "stage": next_stage, "match_id": next_match["match_id"]}

    def dashboard_view(self) -> dict[str, Any]:
        self._touch_health()
        self._refresh_process_states()
        tournament = self._load_current_tournament()
        current_match = self._load_current_match()
        teams = self._load_teams()
        bots = self._load_bots()
        statuses = self._load_runtime_statuses()
        blockers: list[dict[str, Any]] = []
        draft = None
        report = None
        ready_bots: list[str] = []
        handshake = None
        recent_events: list[dict[str, Any]] = []
        active_match_attachments: list[dict[str, Any]] = []
        if current_match:
            version = int(current_match["match_context_version"])
            preflight_result = self.preflight({"match_id": current_match["match_id"]})
            blockers = preflight_result.get("blockers", [])
            draft = self._load_latest_draft(current_match["match_id"], version)
            ready_bots = self._current_ready_bots(current_match)
            assignments = self._load_pick_assignments(current_match["match_id"], version)
            active_match_attachments = list(self._load_match_attachments(current_match["match_id"]).values())
            handshake = self._build_handshake_diagnostics(current_match, statuses, assignments, blockers)
            recent_events = handshake["recent_events"]
            report_row = self.repos.fetch_one("SELECT * FROM match_reports WHERE match_id = ?", (current_match["match_id"],))
            if report_row:
                report = row_json(report_row, "report_json", {})
        commands = self.repos.fetch_all("SELECT * FROM command_executions ORDER BY issued_at DESC LIMIT 50")
        for row in commands:
            row["payload"] = row_json(row, "payload_json", {})
        overrides = self.repos.fetch_all("SELECT * FROM manual_overrides ORDER BY timestamp DESC LIMIT 50")
        return {
            "ok": True,
            "health": self._decode_health(),
            "teams": teams,
            "bots": bots,
            "runtime_statuses": list(statuses.values()),
            "tournament": tournament,
            "current_match": current_match,
            "current_draft": draft,
            "current_report": report,
            "ready_bots": ready_bots,
            "current_match_ready": preflight_result.get("match_start_allowed", False) if current_match else False,
            "active_match_ready": preflight_result.get("match_start_allowed", False) if current_match else False,
            "blockers": blockers,
            "handshake": handshake,
            "recent_events": recent_events,
            "active_match_attachments": active_match_attachments,
            "commands": commands,
            "overrides": overrides,
        }

    def history_view(self) -> dict[str, Any]:
        tournaments = self.repos.fetch_all("SELECT * FROM tournaments ORDER BY created_at DESC")
        reports = self.repos.fetch_all("SELECT * FROM match_reports ORDER BY match_id DESC")
        for row in tournaments:
            row["team_ids"] = row_json(row, "team_ids_json", [])
        for row in reports:
            row["report"] = row_json(row, "report_json", {})
        return {"ok": True, "tournaments": tournaments, "reports": reports}

    def _policy_loop(self) -> None:
        while not self._policy_stop.wait(POLICY_TICK_SECONDS):
            try:
                with self._lock:
                    self._touch_health()
                    self._refresh_process_states()
                    self._run_operational_cycle()
            except Exception as exc:  # pragma: no cover
                self._log_event(
                    "policy_loop_failed",
                    {"error": str(exc)},
                    entity_type="system",
                    entity_id="policy_loop",
                    error_code=str(exc),
                )

    def start_server(self) -> None:
        if self._server is not None:
            return

        coordinator = self

        class Handler(BaseHTTPRequestHandler):
            def _json_response(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                return json.loads(raw.decode("utf-8")) if raw else {}

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                with coordinator._lock:
                    if parsed.path == "/health":
                        self._json_response(200, coordinator._decode_health())
                        return
                    if parsed.path == "/api/views/dashboard":
                        self._json_response(200, coordinator.dashboard_view())
                        return
                    if parsed.path == "/api/views/history":
                        self._json_response(200, coordinator.history_view())
                        return
                    if parsed.path == "/api/instances":
                        self._json_response(200, {"ok": True, "instances": detect_instances()})
                        return
                self._json_response(404, {"ok": False, "error": "Not found"})

            def do_POST(self) -> None:  # noqa: N802
                payload = self._read_json()
                parsed = urlparse(self.path)
                route_map = {
                    "/api/bots/register": coordinator.upsert_bot,
                    "/api/bots/heartbeat": coordinator.record_heartbeat,
                    "/api/bots/status": coordinator.record_status,
                    "/api/bots/launch": coordinator.launch_bot,
                    "/api/bots/commands/next": coordinator.next_command,
                    "/api/bots/pick-started": coordinator.record_pick_started,
                    "/api/bots/pick-confirmed": coordinator.record_pick_confirmed,
                    "/api/bots/pick-failed": coordinator.record_pick_failed,
                    "/api/bots/error": coordinator.record_error,
                    "/api/messages": coordinator.post_message,
                    "/api/commands/update": coordinator.update_command,
                    "/api/instances/register-build-teams": coordinator.auto_register_and_build_teams,
                    "/api/teams/upsert": coordinator.create_or_update_team,
                    "/api/tournaments/create": coordinator.create_tournament,
                    "/api/quick-match/setup": coordinator.create_quick_match,
                    "/api/live-match/prepare": coordinator.prepare_live_match,
                    "/api/matches/config": coordinator.update_match_config,
                    "/api/matches/runtime/attach": coordinator.attach_runtime_instance,
                    "/api/matches/runtime/detach": coordinator.detach_runtime_instance,
                    "/api/matches/runtime/detach-all": coordinator.detach_match_runtime,
                    "/api/matches/draft/regenerate": coordinator.regenerate_draft,
                    "/api/matches/preflight": coordinator.preflight,
                    "/api/matches/launch-bots": coordinator.launch_match_bots,
                    "/api/matches/start-flow": coordinator.start_match_flow,
                    "/api/matches/recovery/run": coordinator.run_match_recovery,
                    "/api/matches/report/build": lambda body: coordinator.build_report_for_match(body["match_id"]),
                    "/api/tournaments/advance": coordinator.advance_stage,
                    "/api/overrides/apply": coordinator.apply_override,
                }
                handler = route_map.get(parsed.path)
                if handler is None:
                    self._json_response(404, {"ok": False, "error": "Not found"})
                    return
                try:
                    with coordinator._lock:
                        result = handler(payload)
                    self._json_response(200, result)
                except Exception as exc:  # pragma: no cover
                    coordinator._log_event(
                        "api_handler_failed",
                        {"path": parsed.path, "error": str(exc)},
                        error_code=str(exc),
                    )
                    self._json_response(500, {"ok": False, "error": str(exc)})

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="championship-coordinator", daemon=True)
        self._thread.start()
        self._policy_stop.clear()
        self._policy_thread = threading.Thread(target=self._policy_loop, name="championship-policy", daemon=True)
        self._policy_thread.start()

    def stop_server(self) -> None:
        if self._server is None:
            return
        self._policy_stop.set()
        self._server.shutdown()
        self._server.server_close()
        for process in self._bot_processes.values():
            if process.poll() is None:
                process.terminate()
        for handle in self._bot_log_handles.values():
            try:
                handle.close()
            except Exception:
                pass
        if self._policy_thread and self._policy_thread.is_alive():
            self._policy_thread.join(timeout=2)
        self._server = None
        self._thread = None


def main() -> int:
    coordinator = ChampionshipCoordinator()
    coordinator.start_server()
    try:
        while True:
            threading.Event().wait(1.0)
    except KeyboardInterrupt:
        coordinator.stop_server()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
