from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from championship.hub.assets import load_tk_image
from championship.hub.widgets.mode_map_summary import ModeMapSummary
from championship.map_registry import default_map_for_mode, get_map_entry, get_mode_entry, maps_for_mode, ordered_modes
from ui_scrolling import register_mousewheel_target


class DraftPage(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg="#0e0f11")
        self.app = app
        modes = ordered_modes()
        self.mode_var = tk.StringVar(value=modes[0].mode_id)
        self.map_var = tk.StringVar(value=modes[0].maps[0].display_name if modes and modes[0].maps else "")
        self._mode_icons: dict[str, object] = {}
        self._map_images: dict[str, object] = {}
        self._rendered_mode_id: str | None = None
        self._rendered_map_mode_id: str | None = None
        self._rendered_map_names: tuple[str, ...] = ()
        self._last_text_payload: str | None = None
        self._last_status_text: str | None = None
        self._last_summary_key: tuple[str | None, str | None] | None = None

        self.summary_host = tk.Frame(self, bg="#0e0f11")
        self.summary_host.pack(fill="x", padx=16, pady=(16, 8))

        tk.Label(self, text="Mode Pool", bg="#0e0f11", fg="#f5efe8", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16)
        self.mode_grid = tk.Frame(self, bg="#0e0f11")
        self.mode_grid.pack(fill="x", padx=16, pady=(8, 16))

        tk.Label(self, text="Maps", bg="#0e0f11", fg="#f5efe8", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16)
        self.map_grid = tk.Frame(self, bg="#0e0f11")
        self.map_grid.pack(fill="x", padx=16, pady=(8, 16))

        buttons = tk.Frame(self, bg="#0e0f11")
        buttons.pack(fill="x", padx=16, pady=(0, 12))
        tk.Button(buttons, text="Apply Mode/Map", command=self.apply_mode_map, bg="#d2452d", fg="#f5efe8", relief="flat").pack(side="left")
        tk.Button(buttons, text="Regenerate Draft", command=self.regenerate_draft, bg="#202228", fg="#f5efe8", relief="flat").pack(side="left", padx=8)

        self.status_label = tk.Label(self, text="", bg="#0e0f11", fg="#bcb5ae", font=("Segoe UI", 10))
        self.status_label.pack(anchor="w", padx=16, pady=(0, 10))

        self.text = tk.Text(self, bg="#17181b", fg="#f5efe8", relief="flat", height=24)
        self.text.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        register_mousewheel_target(self.text)

        self._render_mode_grid()
        self._render_map_grid()
        self._render_summary()

    def current_match_id(self) -> str | None:
        dashboard = self.app.last_dashboard or {}
        match_row = dashboard.get("current_match") or {}
        return match_row.get("match_id")

    def _set_mode(self, mode_id: str) -> None:
        self.mode_var.set(mode_id)
        current_map = get_map_entry(mode_id, self.map_var.get())
        if current_map is None:
            fallback = default_map_for_mode(mode_id)
            self.map_var.set(fallback.display_name if fallback else "")
        self._render_map_grid()
        self._render_summary()

    def _set_map(self, mode_id: str, map_name: str) -> None:
        self.mode_var.set(mode_id)
        self.map_var.set(map_name)
        self._render_map_grid()
        self._render_summary()

    def _render_mode_grid(self) -> None:
        current_mode_id = self.mode_var.get()
        if self._rendered_mode_id == current_mode_id and self.mode_grid.winfo_children():
            for child in self.mode_grid.winfo_children():
                try:
                    mode_id = child._mode_id  # type: ignore[attr-defined]
                except Exception:
                    continue
                selected = current_mode_id == mode_id
                child.configure(bg=get_mode_entry(mode_id).accent if selected else "#202228", activebackground=get_mode_entry(mode_id).accent if selected else "#202228")
            return
        for child in self.mode_grid.winfo_children():
            child.destroy()
        for index, mode in enumerate(ordered_modes()):
            selected = current_mode_id == mode.mode_id
            image = load_tk_image(mode.icon_path, (56, 56), fallback_label=mode.display_name[:1])
            self._mode_icons[mode.mode_id] = image
            card = tk.Button(
                self.mode_grid,
                text=mode.display_name,
                image=image,
                compound="left",
                command=lambda value=mode.mode_id: self._set_mode(value),
                bg=mode.accent if selected else "#202228",
                fg="#f5efe8",
                activebackground=mode.accent,
                activeforeground="#f5efe8",
                relief="flat",
                padx=12,
                pady=10,
                anchor="w",
                font=("Segoe UI", 11, "bold"),
            )
            card._mode_id = mode.mode_id  # type: ignore[attr-defined]
            card.grid(row=index // 4, column=index % 4, padx=6, pady=6, sticky="ew")
            self.mode_grid.grid_columnconfigure(index % 4, weight=1)
        self._rendered_mode_id = current_mode_id

    def _render_map_grid(self) -> None:
        mode_id = self.mode_var.get()
        maps = maps_for_mode(mode_id)
        map_names = tuple(item.display_name for item in maps)
        if self._rendered_map_mode_id == mode_id and self._rendered_map_names == map_names and self.map_grid.winfo_children():
            for child in self.map_grid.winfo_children():
                try:
                    map_name = child._map_name  # type: ignore[attr-defined]
                except Exception:
                    continue
                selected = self.map_var.get() == map_name
                child.configure(
                    bg="#2a2e36" if selected else "#17181b",
                    highlightbackground="#d2452d" if selected else "#31333a",
                    highlightthickness=2 if selected else 1,
                )
                for grandchild in child.winfo_children():
                    if isinstance(grandchild, tk.Label):
                        grandchild.configure(bg=child["bg"])
                    elif isinstance(grandchild, tk.Button):
                        grandchild.configure(bg=child["bg"], activebackground=child["bg"])
            return
        for child in self.map_grid.winfo_children():
            child.destroy()
        if not maps:
            tk.Label(self.map_grid, text="No maps available for this mode.", bg="#0e0f11", fg="#bcb5ae", font=("Segoe UI", 11)).pack(anchor="w")
            return

        for index, item in enumerate(maps):
            selected = self.map_var.get() == item.display_name
            frame = tk.Frame(
                self.map_grid,
                bg="#2a2e36" if selected else "#17181b",
                highlightbackground="#d2452d" if selected else "#31333a",
                highlightthickness=2 if selected else 1,
            )
            frame._map_name = item.display_name  # type: ignore[attr-defined]
            frame.grid(row=index // 4, column=index % 4, padx=8, pady=8, sticky="nsew")
            self.map_grid.grid_columnconfigure(index % 4, weight=1)
            image = load_tk_image(item.preview_path, (128, 193), fallback_label=item.display_name[:2])
            self._map_images[f"{mode_id}:{item.map_id}"] = image
            button = tk.Button(
                frame,
                image=image,
                command=lambda selected_mode=mode_id, map_name=item.display_name: self._set_map(selected_mode, map_name),
                bg=frame["bg"],
                activebackground=frame["bg"],
                relief="flat",
                bd=0,
                highlightthickness=0,
            )
            button.pack(padx=8, pady=(8, 6))
            tk.Label(
                frame,
                text=item.display_name,
                bg=frame["bg"],
                fg="#f5efe8",
                font=("Segoe UI", 10, "bold"),
                wraplength=132,
                justify="center",
            ).pack(padx=8, pady=(0, 8))
        self._rendered_map_mode_id = mode_id
        self._rendered_map_names = map_names

    def _render_summary(self) -> None:
        key = (self.mode_var.get(), self.map_var.get())
        if not hasattr(self, "summary_widget"):
            self.summary_widget = ModeMapSummary(
                self.summary_host,
                mode_id=self.mode_var.get(),
                map_name=self.map_var.get(),
                title="Current Selection",
            )
            self.summary_widget.pack(fill="x")
            self._last_summary_key = key
            return
        if self._last_summary_key != key:
            self.summary_widget.refresh(mode_id=self.mode_var.get(), map_name=self.map_var.get())
            self._last_summary_key = key

    def apply_mode_map(self) -> None:
        match_id = self.current_match_id()
        if not match_id:
            messagebox.showerror("Draft", "Нет активного матча.")
            return
        mode_entry = get_mode_entry(self.mode_var.get())
        map_entry = get_map_entry(self.mode_var.get(), self.map_var.get())
        if mode_entry is None or map_entry is None:
            messagebox.showerror("Draft", "Сначала выбери режим и карту.")
            return
        self.app.run_api_post(
            "/api/matches/config",
            {"match_id": match_id, "mode": mode_entry.mode_id, "map_name": map_entry.display_name, "reason": "hub_mode_map_change"},
            label="apply_mode_map",
            error_title="Draft",
        )

    def regenerate_draft(self) -> None:
        match_id = self.current_match_id()
        if not match_id:
            messagebox.showerror("Draft", "Нет активного матча.")
            return
        self.app.run_api_post(
            "/api/matches/draft/regenerate",
            {"match_id": match_id},
            label="regenerate_draft",
            error_title="Draft",
        )

    def refresh(self, dashboard: dict) -> None:
        match_row = dashboard.get("current_match") or {}
        draft = dashboard.get("current_draft") or {}
        mode_entry = get_mode_entry(match_row.get("mode")) or ordered_modes()[0]
        self.mode_var.set(mode_entry.mode_id)
        map_entry = get_map_entry(mode_entry.mode_id, match_row.get("map_name")) or default_map_for_mode(mode_entry.mode_id)
        self.map_var.set(map_entry.display_name if map_entry else "")
        self._render_mode_grid()
        self._render_map_grid()
        self._render_summary()

        if match_row.get("mode") and match_row.get("map_name"):
            status_text = f"Applied to coordinator: {mode_entry.display_name} / {match_row.get('map_name')}  |  context {match_row.get('match_context_version', '-')}"
        else:
            status_text = "Choose a mode and map, then apply them to the active match."
        if status_text != self._last_status_text:
            self.status_label.configure(text=status_text)
            self._last_status_text = status_text

        if draft:
            text_payload = json_like(draft)
        else:
            text_payload = "No draft generated yet. Apply a mode/map and regenerate draft."
        if text_payload != self._last_text_payload:
            self.text.delete("1.0", "end")
            self.text.insert("end", text_payload)
            self._last_text_payload = text_payload


def json_like(data: dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)
