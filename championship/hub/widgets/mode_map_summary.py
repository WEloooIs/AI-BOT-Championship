from __future__ import annotations

import tkinter as tk

from championship.hub.assets import load_tk_image
from championship.map_registry import default_map_for_mode, get_map_entry, get_mode_entry


class ModeMapSummary(tk.Frame):
    def __init__(
        self,
        master,
        *,
        mode_id: str | None,
        map_name: str | None,
        title: str | None = None,
        compact: bool = False,
    ) -> None:
        super().__init__(master, bg="#202228", highlightbackground="#31333a", highlightthickness=1)
        self.title = title
        self.compact = compact
        self.title_label: tk.Label | None = None

        if title:
            self.title_label = tk.Label(self, text=title, bg="#202228", fg="#bcb5ae", font=("Segoe UI", 10, "bold"))
            self.title_label.pack(anchor="w", padx=12, pady=(10, 0))

        body = tk.Frame(self, bg="#202228")
        body.pack(fill="x", padx=12, pady=12)

        self.icon_size = (52, 52) if compact else (72, 72)
        self.preview_size = (120, 120) if compact else (156, 156)
        self.mode_icon_label = tk.Label(body, bg="#202228")
        self.mode_icon_label.pack(side="left", padx=(0, 12))

        text = tk.Frame(body, bg="#202228")
        text.pack(side="left", fill="both", expand=True)
        self.mode_name_label = tk.Label(text, bg="#202228", fg="#f5efe8", font=("Segoe UI", 16 if compact else 20, "bold"), anchor="w")
        self.mode_name_label.pack(anchor="w")
        self.mode_subtitle_label = tk.Label(text, bg="#202228", fg="#bcb5ae", font=("Segoe UI", 10 if compact else 11), anchor="w")
        self.mode_subtitle_label.pack(anchor="w", pady=(2, 8))
        self.map_name_label = tk.Label(text, bg="#202228", fg="#f5efe8", font=("Segoe UI", 12 if compact else 14, "bold"), anchor="w")
        self.map_name_label.pack(anchor="w")
        self.map_id_label = tk.Label(text, bg="#202228", fg="#8f97a3", font=("Consolas", 9))
        self.map_preview_label = tk.Label(body, bg="#202228")
        self.map_preview_label.pack(side="right", padx=(12, 0))
        self._mode_icon = None
        self._map_preview = None
        self.refresh(mode_id=mode_id, map_name=map_name)

    def refresh(self, *, mode_id: str | None, map_name: str | None) -> None:
        mode_entry = get_mode_entry(mode_id)
        map_entry = get_map_entry(mode_id, map_name)
        if map_entry is None and mode_entry is not None:
            map_entry = default_map_for_mode(mode_id)
        self._mode_icon = load_tk_image(mode_entry.icon_path if mode_entry else None, self.icon_size, fallback_label="M")
        self._map_preview = load_tk_image(map_entry.preview_path if map_entry else None, self.preview_size, fallback_label="MAP")
        self.mode_icon_label.configure(image=self._mode_icon)
        self.map_preview_label.configure(image=self._map_preview)
        self.mode_name_label.configure(text=mode_entry.display_name if mode_entry else "Mode not selected")
        self.mode_subtitle_label.configure(text=mode_entry.subtitle if mode_entry else "Choose a mode first")
        self.map_name_label.configure(text=map_entry.display_name if map_entry else (map_name or "Map not selected"))
        if map_entry:
            self.map_id_label.configure(text=map_entry.map_id)
            if not self.map_id_label.winfo_manager():
                self.map_id_label.pack(anchor="w", pady=(4, 0))
        elif self.map_id_label.winfo_manager():
            self.map_id_label.pack_forget()
