from __future__ import annotations

import platform
import tkinter as tk
from tkinter import ttk


def _wheel_units_from_event(event) -> int:
    num = getattr(event, "num", None)
    if num == 4:
        return -1
    if num == 5:
        return 1
    delta = getattr(event, "delta", 0)
    if delta == 0:
        return 0
    if platform.system() == "Darwin":
        return int(-delta)
    return int(-delta / 120)


def register_mousewheel_target(widget, target=None) -> None:
    setattr(widget, "_wheel_scroll_target", target or widget)


def _resolve_scroll_target(widget):
    current = widget
    while current is not None:
        target = getattr(current, "_wheel_scroll_target", None)
        if target is not None:
            return target
        current = getattr(current, "master", None)
    return None


def install_mousewheel_support(root: tk.Misc) -> None:
    if getattr(root, "_wheel_support_installed", False):
        return

    def handle(event) -> str | None:
        try:
            widget = root.winfo_containing(event.x_root, event.y_root) or event.widget
        except Exception:
            widget = event.widget
        target = _resolve_scroll_target(widget)
        if target is None:
            return None
        units = _wheel_units_from_event(event)
        if units == 0:
            return "break"
        try:
            target.yview_scroll(units, "units")
        except Exception:
            return None
        return "break"

    root.bind_all("<MouseWheel>", handle, add="+")
    root.bind_all("<Shift-MouseWheel>", handle, add="+")
    root.bind_all("<Button-4>", handle, add="+")
    root.bind_all("<Button-5>", handle, add="+")
    setattr(root, "_wheel_support_installed", True)


class ScrollableFrame(tk.Frame):
    def __init__(self, master, bg_color: str) -> None:
        super().__init__(master, bg=bg_color, highlightthickness=0)
        self.canvas = tk.Canvas(self, bg=bg_color, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = tk.Frame(self.canvas, bg=bg_color)
        self._window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self._force_top_on_next_layout = False
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        register_mousewheel_target(self, self.canvas)
        register_mousewheel_target(self.canvas, self.canvas)
        register_mousewheel_target(self.content, self.canvas)

    def _on_content_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        if self._force_top_on_next_layout:
            self._force_top_on_next_layout = False
            try:
                self.canvas.yview_moveto(0.0)
            except Exception:
                return

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._window_id, width=event.width)

    def scroll_to_top(self) -> None:
        self._force_top_on_next_layout = True
        try:
            self.update_idletasks()
            self.canvas.yview_moveto(0.0)
            self.after_idle(lambda: self.canvas.yview_moveto(0.0))
            self.after(25, lambda: self.canvas.yview_moveto(0.0))
        except Exception:
            return


class ScrollablePageHost(tk.Frame):
    def __init__(self, master, bg_color: str) -> None:
        super().__init__(master, bg=bg_color)
        self.scroll = ScrollableFrame(self, bg_color)
        self.scroll.pack(fill="both", expand=True)
        self.content = self.scroll.content
        register_mousewheel_target(self, self.scroll.canvas)

    def scroll_to_top(self) -> None:
        self.scroll.scroll_to_top()
