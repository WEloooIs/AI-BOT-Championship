from __future__ import annotations

import tkinter as tk


class TeamsPage(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg="#0e0f11")
        self.app = app
        self.rows: list[dict[str, tk.Entry]] = []
        for index in range(4):
            card = tk.LabelFrame(self, text=f"Team {index + 1}", bg="#17181b", fg="#f5efe8", font=("Segoe UI", 11, "bold"))
            card.pack(fill="x", padx=16, pady=8)
            fields = {}
            for label in ("team_id", "name", "color", "bot_1", "bot_2", "bot_3"):
                tk.Label(card, text=label, bg="#17181b", fg="#bcb5ae").pack(anchor="w", padx=10, pady=(8 if label == "team_id" else 4, 0))
                entry = tk.Entry(card, bg="#202228", fg="#f5efe8", insertbackground="#f5efe8", relief="flat")
                entry.pack(fill="x", padx=10, pady=4)
                fields[label] = entry
            tk.Button(card, text="Save Team", command=lambda e=fields: self.save_team(e), bg="#d2452d", fg="#f5efe8", relief="flat").pack(anchor="e", padx=10, pady=10)
            self.rows.append(fields)

    def save_team(self, fields: dict[str, tk.Entry]) -> None:
        payload = {
            "team_id": fields["team_id"].get().strip(),
            "name": fields["name"].get().strip(),
            "color": fields["color"].get().strip() or "#d2452d",
            "bot_ids": [fields["bot_1"].get().strip(), fields["bot_2"].get().strip(), fields["bot_3"].get().strip()],
        }
        self.app.run_api_post("/api/teams/upsert", payload, label="save_team", error_title="Teams")

    def refresh(self, dashboard: dict) -> None:
        teams = dashboard.get("teams", [])
        for fields, team in zip(self.rows, teams, strict=False):
            fields["team_id"].delete(0, "end")
            fields["team_id"].insert(0, team["team_id"])
            fields["name"].delete(0, "end")
            fields["name"].insert(0, team["name"])
            fields["color"].delete(0, "end")
            fields["color"].insert(0, team["color"])
            bot_ids = team.get("bot_ids", []) + ["", "", ""]
            for idx, key in enumerate(("bot_1", "bot_2", "bot_3")):
                fields[key].delete(0, "end")
                fields[key].insert(0, bot_ids[idx])
