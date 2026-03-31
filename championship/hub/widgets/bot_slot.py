from __future__ import annotations

import tkinter as tk

from championship.hub.widgets.status_badge import StatusBadge


class BotSlot(tk.Frame):
    def __init__(self, master, title: str, subtitle: str, process_state: str, workflow_state: str, brawler: str | None, role: str | None) -> None:
        super().__init__(master, bg="#202228", bd=0, highlightthickness=1, highlightbackground="#31333a")
        self.brawler_label = tk.Label(self, text=(brawler or "?").upper(), bg="#17181b", fg="#f5efe8", font=("Segoe UI", 14, "bold"), width=8)
        self.brawler_label.pack(pady=(10, 6))
        self.title_label = tk.Label(self, text=title, bg="#202228", fg="#f5efe8", font=("Segoe UI", 11, "bold"))
        self.title_label.pack()
        self.subtitle_label = tk.Label(self, text=subtitle, bg="#202228", fg="#bcb5ae", font=("Segoe UI", 9))
        self.subtitle_label.pack(pady=(2, 4))
        self.role_label = tk.Label(self, bg="#202228", fg="#d2452d", font=("Segoe UI", 9, "bold"))
        if role:
            self.role_label.configure(text=role)
            self.role_label.pack()
        self.badges_frame = tk.Frame(self, bg="#202228")
        self.badges_frame.pack(pady=(8, 10))
        self.process_badge = StatusBadge(self.badges_frame, process_state, process_state)
        self.process_badge.pack(side="left", padx=4)
        self.workflow_badge = StatusBadge(self.badges_frame, workflow_state, workflow_state)
        self.workflow_badge.pack(side="left", padx=4)

    def update_slot(self, *, title: str, subtitle: str, process_state: str, workflow_state: str, brawler: str | None, role: str | None) -> None:
        self.brawler_label.configure(text=(brawler or "?").upper())
        self.title_label.configure(text=title)
        self.subtitle_label.configure(text=subtitle)
        if role:
            self.role_label.configure(text=role)
            if not self.role_label.winfo_manager():
                self.role_label.pack(before=self.badges_frame)
        elif self.role_label.winfo_manager():
            self.role_label.pack_forget()
        self.process_badge.update_state(process_state, process_state)
        self.workflow_badge.update_state(workflow_state, workflow_state)
