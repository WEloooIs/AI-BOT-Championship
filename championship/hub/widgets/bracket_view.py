from __future__ import annotations

import tkinter as tk


class BracketView(tk.LabelFrame):
    def __init__(self, master, tournament: dict | None, reports: list[dict]) -> None:
        super().__init__(master, text="Bracket", bg="#17181b", fg="#f5efe8", font=("Segoe UI", 12, "bold"))
        tournament = tournament or {}
        tk.Label(
            self,
            text=f"Tournament: {tournament.get('name', 'None')}\nStage: {tournament.get('stage', 'idle')}\nStatus: {tournament.get('status', 'idle')}",
            bg="#17181b",
            fg="#f5efe8",
            justify="left",
            font=("Segoe UI", 11),
        ).pack(anchor="w", padx=12, pady=12)
        tk.Label(self, text=f"Reports stored: {len(reports)}", bg="#17181b", fg="#bcb5ae", font=("Segoe UI", 10)).pack(anchor="w", padx=12, pady=(0, 12))
