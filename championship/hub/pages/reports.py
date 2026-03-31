from __future__ import annotations

import json
import tkinter as tk
from ui_scrolling import register_mousewheel_target


class ReportsPage(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg="#0e0f11")
        self.app = app
        self.text = tk.Text(self, bg="#17181b", fg="#f5efe8", relief="flat")
        self.text.pack(fill="both", expand=True, padx=16, pady=16)
        register_mousewheel_target(self.text)
        self._last_text_payload: str | None = None

    def refresh(self, dashboard: dict) -> None:
        report = dashboard.get("current_report")
        if not report:
            payload = "No current report."
        else:
            payload = json.dumps(report, ensure_ascii=False, indent=2)
        if payload == self._last_text_payload:
            return
        self._last_text_payload = payload
        self.text.delete("1.0", "end")
        self.text.insert("end", payload)
