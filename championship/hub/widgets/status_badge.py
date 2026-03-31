from __future__ import annotations

import tkinter as tk


BADGE_COLORS = {
    "active": "#1f7a3d",
    "launching": "#7a5f1f",
    "stale": "#7a5f1f",
    "unresponsive": "#8b2d2d",
    "crashed": "#8b2d2d",
    "error": "#8b2d2d",
    "inactive": "#3a3d44",
    "pick_assigned": "#415a77",
    "pick_in_progress": "#7a5f1f",
    "pick_confirmed": "#1f7a3d",
    "pick_failed": "#8b2d2d",
    "ready": "#1f7a3d",
    "not_ready": "#3a3d44",
}


class StatusBadge(tk.Label):
    def __init__(self, master, text: str, key: str) -> None:
        super().__init__(
            master,
            text=text,
            bg=BADGE_COLORS.get(key, "#3a3d44"),
            fg="#f5efe8",
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=3,
        )

    def update_state(self, text: str, key: str) -> None:
        self.configure(text=text, bg=BADGE_COLORS.get(key, "#3a3d44"))
