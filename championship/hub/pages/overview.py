from __future__ import annotations

import tkinter as tk

from championship.hub.view_models import attachments_lookup, bots_lookup, current_match_teams, runtime_status_lookup
from championship.hub.widgets.blocker_list import BlockerList
from championship.hub.widgets.handshake_panel import HandshakePanel
from championship.hub.widgets.match_center import MatchCenter
from championship.hub.widgets.team_panel import TeamPanel


class OverviewPage(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg="#0e0f11")
        self.app = app
        self.runtime_lookup: dict[str, dict] = {}
        self.bot_lookup: dict[str, dict] = {}
        self.attachment_lookup: dict[str, dict] = {}

        self.top = tk.Frame(self, bg="#0e0f11")
        self.top.pack(fill="both", expand=True, padx=16, pady=16)
        self.left_panel = TeamPanel(self.top, {"name": "Team A", "bot_ids": [], "roles": {}, "color": "#31333a"}, {})
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.match_center = MatchCenter(self.top, None, None, None)
        self.match_center.grid(row=0, column=1, sticky="nsew", padx=12)
        self.right_panel = TeamPanel(self.top, {"name": "Team B", "bot_ids": [], "roles": {}, "color": "#31333a"}, {})
        self.right_panel.grid(row=0, column=2, sticky="nsew", padx=(12, 0))
        self.top.grid_columnconfigure(0, weight=1)
        self.top.grid_columnconfigure(1, weight=1)
        self.top.grid_columnconfigure(2, weight=1)
        self.top.grid_rowconfigure(0, weight=1)
        self.handshake_panel = HandshakePanel(self, None)
        self.handshake_panel.pack(fill="x", padx=16, pady=(0, 16))
        self.blocker_list = BlockerList(self, [])
        self.blocker_list.pack(fill="x", padx=16, pady=(0, 16))

    def refresh(self, dashboard: dict) -> None:
        runtime_lookup = runtime_status_lookup(dashboard)
        bot_lookup = bots_lookup(dashboard)
        attachment_lookup = attachments_lookup(dashboard)
        left, right = current_match_teams(dashboard)
        self.left_panel.refresh(left, runtime_lookup, bot_lookup, attachment_lookup)
        self.right_panel.refresh(right, runtime_lookup, bot_lookup, attachment_lookup)
        self.match_center.refresh(
            dashboard.get("current_match"),
            dashboard.get("tournament"),
            dashboard.get("health"),
            ready_bots=dashboard.get("ready_bots", []),
            match_ready=dashboard.get("current_match_ready", False),
            handshake=dashboard.get("handshake"),
            attachments=dashboard.get("active_match_attachments", []),
        )
        self.handshake_panel.refresh(dashboard.get("handshake"))
        self.blocker_list.refresh(dashboard.get("blockers", []))
