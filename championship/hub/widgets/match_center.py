from __future__ import annotations

import tkinter as tk

from championship.hub.widgets.status_badge import StatusBadge
from championship.hub.widgets.mode_map_summary import ModeMapSummary


class MatchCenter(tk.LabelFrame):
    def __init__(
        self,
        master,
        match_row: dict | None,
        tournament_row: dict | None,
        health: dict | None,
        *,
        ready_bots: list[str] | None = None,
        match_ready: bool = False,
        handshake: dict | None = None,
        attachments: list[dict] | None = None,
    ) -> None:
        super().__init__(master, text="Match Center", bg="#17181b", fg="#f5efe8", font=("Segoe UI", 12, "bold"))
        header = tk.Frame(self, bg="#17181b")
        header.pack(fill="x", padx=12, pady=(12, 8))
        self.stage_label = tk.Label(header, bg="#17181b", fg="#d2452d", font=("Segoe UI", 18, "bold"))
        self.stage_label.pack(side="left")
        self.coordinator_badge = StatusBadge(header, "coordinator", "error")
        self.coordinator_badge.pack(side="right", padx=4)
        self.db_badge = StatusBadge(header, "db", "error")
        self.db_badge.pack(side="right", padx=4)
        self.observer_badge = StatusBadge(header, "observer", "error")
        self.observer_badge.pack(side="right", padx=4)
        body = tk.Frame(self, bg="#17181b")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.summary = ModeMapSummary(
            body,
            mode_id=None,
            map_name=None,
            compact=True,
        )
        self.summary.pack(fill="x", pady=4)
        self.meta_label = tk.Label(body, bg="#17181b", fg="#bcb5ae", justify="left", anchor="w", font=("Consolas", 10))
        self.meta_label.pack(fill="x", pady=(10, 0))
        self.refresh(
            match_row,
            tournament_row,
            health,
            ready_bots=ready_bots,
            match_ready=match_ready,
            handshake=handshake,
            attachments=attachments,
        )

    def refresh(
        self,
        match_row: dict | None,
        tournament_row: dict | None,
        health: dict | None,
        *,
        ready_bots: list[str] | None = None,
        match_ready: bool = False,
        handshake: dict | None = None,
        attachments: list[dict] | None = None,
    ) -> None:
        match_row = match_row or {}
        tournament_row = tournament_row or {}
        health = health or {}
        handshake = handshake or {}
        ready_bots = ready_bots or []
        attachments = attachments or []
        self.stage_label.configure(text=(tournament_row.get("stage") or "idle").upper())
        self.coordinator_badge.update_state("coordinator", "active" if health.get("coordinator_alive") else "error")
        self.db_badge.update_state("db", "active" if health.get("database_writable") else "error")
        self.observer_badge.update_state("observer", "active" if health.get("observer_healthy") else "error")
        self.summary.refresh(mode_id=match_row.get("mode"), map_name=match_row.get("map_name"))
        meta = (
            f"match_id: {match_row.get('match_id', '-')}\n"
            f"context_version: {match_row.get('match_context_version', '-')}\n"
            f"status: {match_row.get('status', '-')}\n"
            f"handshake_phase: {handshake.get('phase', '-')}\n"
            f"host_bot: {handshake.get('current_host_bot_id', '-')}\n"
            f"attached_runtime: {len(attachments)} / 6\n"
            f"ready_bots: {len(ready_bots)} / 6\n"
            f"match_ready: {'yes' if match_ready else 'no'}"
        )
        self.meta_label.configure(text=meta)
