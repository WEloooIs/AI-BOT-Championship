from __future__ import annotations

import json
import tkinter as tk
from ui_scrolling import register_mousewheel_target


class HistoryPage(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg="#0e0f11")
        self.app = app
        self.text = tk.Text(self, bg="#17181b", fg="#f5efe8", relief="flat")
        self.text.pack(fill="both", expand=True, padx=16, pady=16)
        register_mousewheel_target(self.text)
        self._last_text_payload: str | None = None

    def refresh(self, history_data: dict) -> None:
        text_payload = json.dumps(history_data, ensure_ascii=False, indent=2)
        if text_payload == self._last_text_payload:
            return
        self._last_text_payload = text_payload
        self.text.delete("1.0", "end")
        self.text.insert("end", text_payload)
