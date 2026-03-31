from __future__ import annotations

import tkinter as tk


class BlockerList(tk.LabelFrame):
    def __init__(self, master, blockers: list[dict]) -> None:
        super().__init__(master, text="Start Blockers", bg="#17181b", fg="#f5efe8", font=("Segoe UI", 12, "bold"))
        self.body = tk.Frame(self, bg="#17181b")
        self.body.pack(fill="x", expand=True)
        self._last_signature = None
        self.refresh(blockers)

    def refresh(self, blockers: list[dict]) -> None:
        signature = tuple((b.get("code"), b.get("severity"), b.get("message")) for b in blockers)
        if signature == self._last_signature:
            return
        self._last_signature = signature
        for child in self.body.winfo_children():
            child.destroy()
        if not blockers:
            tk.Label(
                self.body,
                text="Нет блокеров. Старт матча разрешён.",
                bg="#17181b",
                fg="#9fd8b5",
                font=("Segoe UI", 11),
            ).pack(anchor="w", padx=12, pady=10)
            return
        for blocker in blockers:
            text = f"[{blocker['code']}] {blocker['message']}"
            tk.Label(
                self.body,
                text=text,
                bg="#17181b",
                fg="#f0c4b5" if blocker["severity"] == "warning" else "#ff8a80",
                anchor="w",
                justify="left",
                wraplength=520,
                font=("Segoe UI", 10),
            ).pack(fill="x", padx=12, pady=4)
