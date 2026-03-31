from __future__ import annotations

import tkinter as tk

from championship.hub.view_models import bots_lookup, current_match_teams, runtime_status_lookup
from championship.hub.widgets.match_center import MatchCenter
from championship.hub.widgets.team_panel import TeamPanel


class BroadcastPage(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg="#0e0f11")
        self.app = app
        self._last_signature: tuple | None = None
        self.shell = tk.Frame(self, bg="#0e0f11")
        self.shell.pack(fill="both", expand=True, padx=20, pady=20)
        self.left_panel = TeamPanel(self.shell, {"name": "Team A", "bot_ids": [], "roles": {}, "color": "#31333a"}, {}, {})
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        self.match_center = MatchCenter(self.shell, None, None, None)
        self.match_center.grid(row=0, column=1, sticky="nsew", padx=18)
        self.right_panel = TeamPanel(self.shell, {"name": "Team B", "bot_ids": [], "roles": {}, "color": "#31333a"}, {}, {})
        self.right_panel.grid(row=0, column=2, sticky="nsew", padx=(18, 0))
        self.shell.grid_columnconfigure(0, weight=1)
        self.shell.grid_columnconfigure(1, weight=1)
        self.shell.grid_columnconfigure(2, weight=1)

    def refresh(self, dashboard: dict) -> None:
        left, right = current_match_teams(dashboard)
        runtime = runtime_status_lookup(dashboard)
        bot_lookup = bots_lookup(dashboard)
        signature = (
            tuple(left.get("bot_ids", [])),
            tuple(right.get("bot_ids", [])),
            tuple((row.get("bot_id"), row.get("process_state"), row.get("workflow_state"), row.get("selected_brawler")) for row in dashboard.get("runtime_statuses", [])),
            (dashboard.get("current_match") or {}).get("match_id"),
            (dashboard.get("current_match") or {}).get("match_context_version"),
        )
        if signature == self._last_signature:
            return
        self._last_signature = signature
        self.left_panel.refresh(left, runtime, bot_lookup)
        self.right_panel.refresh(right, runtime, bot_lookup)
        self.match_center.refresh(dashboard.get("current_match"), dashboard.get("tournament"), dashboard.get("health"))
