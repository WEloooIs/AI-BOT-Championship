from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

from championship.hub.api import CoordinatorApi
from championship.hub.pages.broadcast import BroadcastPage
from championship.hub.pages.draft import DraftPage
from championship.hub.pages.history import HistoryPage
from championship.hub.pages.instances import InstancesPage
from championship.hub.pages.logs import LogsPage
from championship.hub.pages.messages import MessagesPage
from championship.hub.pages.overview import OverviewPage
from championship.hub.pages.reports import ReportsPage
from championship.hub.pages.settings import SettingsPage
from championship.hub.pages.teams import TeamsPage
from championship.hub.pages.tournament import TournamentPage
from ui_scrolling import ScrollablePageHost, install_mousewheel_support


BG = "#0e0f11"
SIDEBAR = "#101114"
PANEL = "#17181b"
ACCENT = "#d2452d"
TEXT = "#f5efe8"
TEXT_SUBTLE = "#bcb5ae"


class ChampionshipHubApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Pyla Championship Hub")
        self.geometry("1540x940")
        self.minsize(1280, 780)
        self.configure(bg=BG)
        install_mousewheel_support(self)
        self.api = CoordinatorApi()
        self.last_dashboard: dict | None = None
        self.last_history: dict | None = None
        self.last_health: dict | None = None
        self.last_backend_error: str | None = None
        self.last_action_error: str | None = None
        self._refresh_job: str | None = None
        self._refresh_inflight = False
        self._startup_inflight = False
        self.refresh_interval_ms = 8000
        self.nav_buttons: dict[str, tk.Button] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.current_page = ""
        self._build_shell()
        self.show_page("overview")
        self._set_status_line()
        self.diagnostics_line.configure(text="Starting coordinator...")
        self._start_backend()

    def _compact_diagnostic(self, text: str | None) -> str:
        if not text:
            return ""
        compact = " ".join(str(text).split())
        lowered = compact.lower()
        if "powershell" in lowered and ("get-nettcpconnection" in lowered or "win32_process" in lowered):
            return "instance detection probe timed out"
        compact = compact.replace("Command '['powershell'", "powershell")
        compact = compact.replace("Command '['", "")
        compact = compact.replace("'] timed out after", " timed out after")
        compact = compact.replace("returned non-zero exit status", "failed rc=")
        if len(compact) > 220:
            compact = compact[:217] + "..."
        return compact

    def _build_shell(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = tk.Frame(self, bg=SIDEBAR, width=260)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        content = tk.Frame(self, bg=BG)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_rowconfigure(2, weight=1)
        content.grid_columnconfigure(0, weight=1)
        self.content = content

        tk.Label(sidebar, text="PYLA", bg=SIDEBAR, fg=TEXT, font=("Segoe UI", 28, "bold")).pack(anchor="w", padx=22, pady=(24, 4))
        tk.Label(sidebar, text="Championship Control Center", bg=SIDEBAR, fg=TEXT_SUBTLE, font=("Segoe UI", 11)).pack(anchor="w", padx=22)
        tk.Button(sidebar, text="Refresh", command=self.refresh_all, bg=ACCENT, fg=TEXT, relief="flat").pack(anchor="w", padx=22, pady=18)

        nav = tk.Frame(sidebar, bg=SIDEBAR)
        nav.pack(fill="x", padx=14)
        for key, label in [
            ("overview", "Overview"),
            ("instances", "Instances"),
            ("teams", "Teams"),
            ("draft", "Draft / Picks"),
            ("tournament", "Tournament"),
            ("reports", "Observer Reports"),
            ("history", "History"),
            ("messages", "Communication"),
            ("logs", "Logs"),
            ("settings", "Settings"),
            ("broadcast", "Broadcast"),
        ]:
            button = tk.Button(nav, text=label, command=lambda k=key: self.show_page(k), bg=SIDEBAR, fg=TEXT, relief="flat", anchor="w", padx=12, pady=10)
            button.pack(fill="x", pady=2)
            self.nav_buttons[key] = button

        self.status_line = tk.Label(content, text="", bg=BG, fg=TEXT_SUBTLE, font=("Segoe UI", 11))
        self.status_line.grid(row=0, column=0, sticky="w", padx=18, pady=10)
        self.diagnostics_line = tk.Label(content, text="", bg=BG, fg="#d9a37c", font=("Consolas", 9), anchor="w", justify="left")
        self.diagnostics_line.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 6))
        self.page_host = tk.Frame(content, bg=BG)
        self.page_host.grid(row=2, column=0, sticky="nsew")

    def _set_status_line(self) -> None:
        health = self.last_health or (self.last_dashboard or {}).get("health") or {}
        self.status_line.configure(
            text=(
                f"Coordinator: {'OK' if health.get('coordinator_alive') else 'DOWN'}  |  "
                f"DB: {'OK' if health.get('database_writable') else 'DOWN'}  |  "
                f"Observer: {'OK' if health.get('observer_healthy') else 'DEGRADED'}"
            )
        )

    def _make_page(self, key: str) -> tk.Frame:
        page_map = {
            "overview": OverviewPage,
            "instances": InstancesPage,
            "teams": TeamsPage,
            "draft": DraftPage,
            "tournament": TournamentPage,
            "reports": ReportsPage,
            "history": HistoryPage,
            "messages": MessagesPage,
            "settings": SettingsPage,
            "broadcast": BroadcastPage,
            "logs": LogsPage,
        }
        scrollable_pages = {"overview", "teams", "draft", "tournament", "broadcast"}
        if key in scrollable_pages:
            host = ScrollablePageHost(self.page_host, BG)
            inner = page_map[key](host.content, self)
            inner.pack(fill="both", expand=True)
            host.refresh = inner.refresh  # type: ignore[attr-defined]
            page = host
        else:
            page = page_map[key](self.page_host, self)
        self.pages[key] = page
        return page

    def show_page(self, key: str) -> None:
        if self.current_page == key:
            page = self.pages.get(key)
            if page is not None and hasattr(page, "scroll_to_top"):
                self.after(0, page.scroll_to_top)
            return
        self.current_page = key
        for nav_key, button in self.nav_buttons.items():
            button.configure(bg=ACCENT if nav_key == key else SIDEBAR)
        for child in self.page_host.winfo_children():
            child.grid_forget()
        page = self.pages.get(key) or self._make_page(key)
        page.grid(row=0, column=0, sticky="nsew")
        if hasattr(page, "scroll_to_top"):
            self.after(0, page.scroll_to_top)
        self.page_host.grid_rowconfigure(0, weight=1)
        self.page_host.grid_columnconfigure(0, weight=1)
        if (key == "history" and self.last_history is not None) or (key != "history" and self.last_dashboard is not None):
            self.refresh_current_page(force=True)
            if hasattr(page, "scroll_to_top"):
                self.after(1, page.scroll_to_top)

    def _start_backend(self) -> None:
        if self._startup_inflight:
            return
        self._startup_inflight = True

        def worker() -> None:
            health_result = None
            dashboard_result = None
            history_result = None
            error_text = None
            try:
                self.api.ensure_running()
                health_result = self.api.health()
                dashboard_result = self.api.dashboard()
                if self.current_page == "history":
                    history_result = self.api.history()
            except Exception as exc:
                error_text = f"startup: {exc}"
            self.after(0, lambda: self._apply_refresh_result(health_result, dashboard_result, history_result, error_text, source="startup"))

        threading.Thread(target=worker, name="championship-hub-startup", daemon=True).start()

    def refresh_all(self) -> None:
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except Exception:
                pass
            self._refresh_job = None
        if self._startup_inflight:
            self._refresh_job = self.after(self.refresh_interval_ms, self.refresh_all)
            return
        if self._refresh_inflight:
            self._refresh_job = self.after(self.refresh_interval_ms, self.refresh_all)
            return
        self._refresh_inflight = True
        include_history = self.current_page == "history" or self.last_history is None

        def worker() -> None:
            health_result = None
            dashboard_result = None
            history_result = None
            error_text = None
            try:
                self.api.ensure_running()
                health_result = self.api.health()
                if not health_result.get("coordinator_alive"):
                    error_text = f"{self.current_page}: coordinator health unavailable"
                dashboard_result = self.api.dashboard()
                if not dashboard_result.get("ok"):
                    error_text = f"{self.current_page}: dashboard: {dashboard_result.get('error', 'unknown error')}"
                if include_history:
                    history_result = self.api.history()
                    if not history_result.get("ok") and not error_text:
                        error_text = f"{self.current_page}: history: {history_result.get('error', 'unknown error')}"
            except Exception as exc:
                error_text = f"{self.current_page}: refresh_all: {exc}"
            self.after(0, lambda: self._apply_refresh_result(health_result, dashboard_result, history_result, error_text, source="poll"))

        threading.Thread(target=worker, name="championship-hub-refresh", daemon=True).start()

    def _apply_refresh_result(
        self,
        health_result: dict | None,
        dashboard_result: dict | None,
        history_result: dict | None,
        error_text: str | None,
        *,
        source: str,
    ) -> None:
        self._refresh_inflight = False
        self._startup_inflight = False
        if health_result and "coordinator_alive" in health_result:
            self.last_health = health_result
        if dashboard_result and dashboard_result.get("ok"):
            self.last_dashboard = dashboard_result
            self.last_backend_error = None
        elif error_text:
            self.last_backend_error = self._compact_diagnostic(error_text)
        if history_result and history_result.get("ok"):
            self.last_history = history_result
        elif history_result and not history_result.get("ok") and not error_text:
            self.last_backend_error = self._compact_diagnostic(
                f"{self.current_page}: history: {history_result.get('error', 'unknown error')}"
            )
        self._set_status_line()
        diagnostics = self.last_action_error or self.last_backend_error or ""
        self.diagnostics_line.configure(text=diagnostics)
        if dashboard_result and dashboard_result.get("ok"):
            self.refresh_current_page(force=True)
        elif source == "startup" and self.last_dashboard is not None:
            self.refresh_current_page(force=True)
        self._refresh_job = self.after(self.refresh_interval_ms, self.refresh_all)

    def run_background_task(
        self,
        label: str,
        task,
        *,
        on_success=None,
        on_complete=None,
        refresh_after: bool = False,
        error_title: str | None = None,
        announce: bool = True,
        surface_failure: bool = True,
        success_message: str | None = None,
    ) -> None:
        if announce or surface_failure:
            self.last_action_error = None
        if announce:
            self.diagnostics_line.configure(text=f"{label}: running...")

        def worker() -> None:
            try:
                result = task()
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            self.after(
                0,
                lambda: self._apply_action_result(
                    label,
                    result,
                    refresh_after,
                    on_success,
                    on_complete,
                    error_title,
                    announce,
                    surface_failure,
                    success_message,
                ),
            )

        threading.Thread(target=worker, name=f"championship-task-{label}", daemon=True).start()

    def run_api_post(
        self,
        path: str,
        payload: dict,
        *,
        label: str,
        refresh_after: bool = True,
        on_success=None,
        on_complete=None,
        error_title: str | None = None,
        announce: bool = True,
        surface_failure: bool = True,
        success_message: str | None = None,
    ) -> None:
        self.run_background_task(
            label,
            lambda: self.api.post(path, payload),
            on_success=on_success,
            on_complete=on_complete,
            refresh_after=refresh_after,
            error_title=error_title,
            announce=announce,
            surface_failure=surface_failure,
            success_message=success_message,
        )

    def _apply_action_result(
        self,
        label: str,
        result: dict,
        refresh_after: bool,
        on_success,
        on_complete,
        error_title: str | None,
        announce: bool,
        surface_failure: bool,
        success_message: str | None,
    ) -> None:
        if on_complete:
            on_complete(result)
        if result.get("ok"):
            if announce or surface_failure:
                self.last_action_error = None
            if announce:
                self.diagnostics_line.configure(text=success_message or f"{label}: ok")
            if on_success:
                on_success(result)
            if refresh_after:
                self.refresh_all()
            return
        error_text = result.get("error", "unknown error")
        if surface_failure:
            self.last_action_error = self._compact_diagnostic(f"{label}: {error_text}")
            self.diagnostics_line.configure(text=self.last_action_error)
        if error_title:
            messagebox.showerror(error_title, error_text)

    def refresh_current_page(self, force: bool = False) -> None:
        page = self.pages.get(self.current_page)
        if page is None:
            return
        if self.current_page in {"instances", "tournament"} and not force:
            return
        if self.current_page == "history":
            page.refresh(self.last_history or {})
        else:
            page.refresh(self.last_dashboard or {})


def main() -> None:
    app = ChampionshipHubApp()
    app.mainloop()


if __name__ == "__main__":
    main()
