from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from instance_identity import resolve_instances_cached
from ui_scrolling import register_mousewheel_target


class InstancesPage(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg="#0e0f11")
        self.app = app
        self.instances: list[dict] = []
        self._last_signature: tuple[tuple[str, str, str, str, str], ...] | None = None
        self._load_inflight = False
        self._last_error: str | None = None
        toolbar = tk.Frame(self, bg="#0e0f11")
        toolbar.pack(fill="x", padx=16, pady=12)
        tk.Button(toolbar, text="Refresh", command=self.manual_refresh, bg="#d2452d", fg="#f5efe8", relief="flat").pack(side="left")
        tk.Button(toolbar, text="Register All Instances", command=self.register_all, bg="#202228", fg="#f5efe8", relief="flat").pack(side="left", padx=8)
        tk.Button(toolbar, text="Register + Build 2 Teams", command=self.register_and_build_teams, bg="#202228", fg="#f5efe8", relief="flat").pack(side="left", padx=8)
        self.info_label = tk.Label(self, text="", bg="#0e0f11", fg="#bcb5ae", anchor="w", justify="left", font=("Segoe UI", 9))
        self.info_label.pack(fill="x", padx=16, pady=(0, 8))
        self.tree = ttk.Treeview(self, columns=("label", "serial", "vendor", "model", "source"), show="headings", height=16)
        self.tree.column("#0", width=0, stretch=False)
        headings = {
            "label": "Label",
            "serial": "Serial",
            "vendor": "Vendor",
            "model": "Model",
            "source": "Source",
        }
        widths = {
            "label": 420,
            "serial": 210,
            "vendor": 140,
            "model": 140,
            "source": 120,
        }
        for col in ("label", "serial", "vendor", "model", "source"):
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w", stretch=(col == "label"))
        self.tree.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        register_mousewheel_target(self.tree)

    def register_all(self) -> None:
        if not self.instances:
            self.manual_refresh()
            return
        def task() -> dict:
            for item in self.instances:
                serial = str(item["serial"])
                self.app.api.post(
                    "/api/bots/register",
                    {
                        "bot_id": serial.replace(":", "_").replace(".", "_"),
                        "instance_id": serial,
                        "display_name": str(item.get("parsed_player_name") or item.get("display_label") or serial),
                        "platform": "nulls",
                        "metadata": item,
                    },
                )
            return {"ok": True}

        self.app.run_background_task("register_all_instances", task, on_success=lambda _result: self.manual_refresh())

    def _refresh_instances(self, *, force: bool = False) -> None:
        self.instances = resolve_instances_cached(force=force)

    def _populate_tree(self) -> None:
        if self._load_inflight:
            self.info_label.configure(text="Scanning instances...")
        elif self._last_error:
            self.info_label.configure(text=f"Instance scan failed: {self._last_error}")
        elif not self.instances:
            self.info_label.configure(text="No live instances detected.")
        else:
            self.info_label.configure(text=f"Detected {len(self.instances)} live instance(s).")
        signature = tuple(
            (
                str(row.get("display_label", row["serial"])),
                str(row["serial"]),
                str(row.get("vendor", row.get("emulator", "Unknown"))),
                str(row["model"]),
                str(row.get("resolved_name_source", "fallback")),
            )
            for row in self.instances
        )
        if signature == self._last_signature and self.tree.get_children():
            return
        self._last_signature = signature
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.instances:
            self.tree.insert(
                "",
                "end",
                values=(
                    row.get("display_label", row["serial"]),
                    row["serial"],
                    row.get("vendor", row.get("emulator", "Unknown")),
                    row["model"],
                    row.get("resolved_name_source", "fallback"),
                ),
            )

    def manual_refresh(self) -> None:
        if self._load_inflight:
            return
        self._load_inflight = True
        self._last_error = None
        self._populate_tree()
        self.app.run_background_task(
            "instances_refresh",
            lambda: {
                "ok": True,
                "dashboard": self.app.api.dashboard(),
                "instances": resolve_instances_cached(force=True),
            },
            on_success=self._apply_manual_refresh,
            on_complete=self._finish_refresh,
            announce=False,
            surface_failure=False,
        )

    def refresh(self, dashboard: dict) -> None:
        if not self.instances and not self._load_inflight:
            self._load_inflight = True
            self._last_error = None
            self._populate_tree()
            self.app.run_background_task(
                "instances_open",
                lambda: {"ok": True, "instances": resolve_instances_cached(force=False)},
                on_success=self._apply_cached_instances,
                on_complete=self._finish_refresh,
                refresh_after=False,
                announce=False,
                surface_failure=False,
            )
        self._populate_tree()

    def register_and_build_teams(self) -> None:
        if not self.instances:
            self.manual_refresh()
            return
        self.app.run_api_post(
            "/api/instances/register-build-teams",
            {"team_count": 2, "instances": self.instances},
            label="register_build_teams",
            on_success=lambda _result: self.manual_refresh(),
        )

    def _apply_cached_instances(self, result: dict) -> None:
        self.instances = result.get("instances", [])
        self._populate_tree()

    def _apply_manual_refresh(self, result: dict) -> None:
        dashboard = result.get("dashboard")
        if dashboard and dashboard.get("ok"):
            self.app.last_dashboard = dashboard
            self.app.last_backend_error = None
        self.instances = result.get("instances", [])
        self.app._set_status_line()
        self._populate_tree()

    def _finish_refresh(self, result: dict) -> None:
        self._load_inflight = False
        if not result.get("ok"):
            self._last_error = self.app._compact_diagnostic(result.get("error", "unknown error"))
        else:
            self._last_error = None
        self._populate_tree()
