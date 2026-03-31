from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from championship.hub.widgets.blocker_list import BlockerList
from championship.hub.widgets.bracket_view import BracketView
from championship.hub.widgets.mode_map_summary import ModeMapSummary
from instance_identity import resolve_instances_cached


class TournamentPage(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg="#0e0f11")
        self.app = app
        self.instance_rows: dict[str, dict] = {}
        self.attachment_vars: dict[str, tk.StringVar] = {}
        self.pending_attachment_choices: dict[str, str] = {}
        self._detected_instances: list[dict] = []
        self._instances_scan_inflight = False
        self._last_signature: tuple | None = None

        controls = tk.Frame(self, bg="#0e0f11")
        controls.pack(fill="x", padx=16, pady=16)
        tk.Button(controls, text="Prepare Live 3v3", command=self.prepare_live_match, bg="#d2452d", fg="#f5efe8", relief="flat").pack(side="left")
        tk.Button(controls, text="Setup Quick 3v3", command=self.setup_quick_match, bg="#d2452d", fg="#f5efe8", relief="flat").pack(side="left")
        tk.Button(controls, text="Create Tournament From Current Teams", command=self.create_tournament, bg="#d2452d", fg="#f5efe8", relief="flat").pack(side="left", padx=8)
        tk.Button(controls, text="Preflight", command=self.preflight, bg="#202228", fg="#f5efe8", relief="flat").pack(side="left", padx=8)
        tk.Button(controls, text="Launch Match Bots", command=self.launch_match_bots, bg="#202228", fg="#f5efe8", relief="flat").pack(side="left", padx=8)
        tk.Button(controls, text="Start Match Flow", command=self.start_match_flow, bg="#202228", fg="#f5efe8", relief="flat").pack(side="left", padx=8)
        tk.Button(controls, text="Run Recovery", command=self.run_recovery, bg="#202228", fg="#f5efe8", relief="flat").pack(side="left", padx=8)
        tk.Button(controls, text="Build Report", command=self.build_report, bg="#202228", fg="#f5efe8", relief="flat").pack(side="left", padx=8)
        tk.Button(controls, text="Advance Stage", command=self.advance_stage, bg="#202228", fg="#f5efe8", relief="flat").pack(side="left", padx=8)
        tk.Button(controls, text="Detach All Runtime", command=self.detach_all_runtime, bg="#8b2d2d", fg="#f5efe8", relief="flat").pack(side="left", padx=8)

        tk.Label(controls, text="Manual winner team_id:", bg="#0e0f11", fg="#bcb5ae").pack(side="left", padx=(18, 6))
        self.manual_winner = tk.Entry(controls, bg="#202228", fg="#f5efe8", insertbackground="#f5efe8", relief="flat", width=16)
        self.manual_winner.pack(side="left")
        tk.Button(controls, text="Apply Winner Override", command=self.apply_winner_override, bg="#8b2d2d", fg="#f5efe8", relief="flat").pack(side="left", padx=8)

        self.body = tk.Frame(self, bg="#0e0f11")
        self.body.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def create_tournament(self) -> None:
        dashboard = self.app.last_dashboard or {}
        team_ids = [row["team_id"] for row in dashboard.get("teams", [])[:4]]
        self.app.run_api_post(
            "/api/tournaments/create",
            {"team_ids": team_ids, "name": "Bot Championship"},
            label="create_tournament",
            error_title="Tournament",
        )

    def current_match_id(self) -> str | None:
        dashboard = self.app.last_dashboard or {}
        return (dashboard.get("current_match") or {}).get("match_id")

    def setup_quick_match(self) -> None:
        dashboard = self.app.last_dashboard or {}
        initial_team_ids = [row["team_id"] for row in dashboard.get("teams", [])[:2]]

        def task() -> dict:
            team_ids = list(initial_team_ids)
            dashboard_result = None
            if len(team_ids) < 2:
                build_result = self.app.api.post("/api/instances/register-build-teams", {"team_count": 2})
                if not build_result.get("ok"):
                    return build_result
                dashboard_result = self.app.api.dashboard()
                if dashboard_result.get("ok"):
                    team_ids = [row["team_id"] for row in dashboard_result.get("teams", [])[:2]]
            result = self.app.api.post("/api/quick-match/setup", {"team_ids": team_ids, "name": "Quick 3v3"})
            if dashboard_result and dashboard_result.get("ok"):
                result["prefetched_dashboard"] = dashboard_result
            return result

        self.app.run_background_task(
            "setup_quick_match",
            task,
            refresh_after=True,
            error_title="Tournament",
            on_success=self._apply_setup_quick_match,
        )

    def prepare_live_match(self) -> None:
        self.app.run_api_post("/api/live-match/prepare", {}, label="prepare_live_match", error_title="Live Match")

    def preflight(self) -> None:
        match_id = self.current_match_id()
        if match_id:
            self.app.run_api_post("/api/matches/preflight", {"match_id": match_id}, label="preflight", error_title="Tournament")

    def launch_match_bots(self) -> None:
        match_id = self.current_match_id()
        if match_id:
            self.app.run_api_post("/api/matches/launch-bots", {"match_id": match_id}, label="launch_match_bots", error_title="Tournament")

    def start_match_flow(self) -> None:
        match_id = self.current_match_id()
        if match_id:
            self.app.run_api_post("/api/matches/start-flow", {"match_id": match_id}, label="start_match_flow", error_title="Match Start")

    def run_recovery(self) -> None:
        match_id = self.current_match_id()
        if match_id:
            self.app.run_api_post("/api/matches/recovery/run", {"match_id": match_id}, label="run_recovery", error_title="Tournament")

    def build_report(self) -> None:
        match_id = self.current_match_id()
        if match_id:
            self.app.run_api_post("/api/matches/report/build", {"match_id": match_id}, label="build_report", error_title="Tournament")

    def advance_stage(self) -> None:
        self.app.run_api_post("/api/tournaments/advance", {}, label="advance_stage", error_title="Tournament")

    def detach_all_runtime(self) -> None:
        match_id = self.current_match_id()
        if match_id:
            self.app.run_api_post("/api/matches/runtime/detach-all", {"match_id": match_id}, label="detach_all_runtime", error_title="Tournament")

    def apply_winner_override(self) -> None:
        match_id = self.current_match_id()
        winner = self.manual_winner.get().strip()
        if not match_id or not winner:
            messagebox.showerror("Tournament", "Current match and winner team_id are required.")
            return
        self.app.run_api_post(
            "/api/overrides/apply",
            {
                "actor": "hub_admin",
                "reason": "manual_winner_override",
                "target_entity": f"{match_id}:{winner}",
                "effect": "set_match_winner",
            },
            label="apply_winner_override",
            error_title="Tournament",
        )

    def _match_bot_rows(self, dashboard: dict) -> list[dict]:
        match = dashboard.get("current_match") or {}
        teams = {row["team_id"]: row for row in dashboard.get("teams", [])}
        bots = {row["bot_id"]: row for row in dashboard.get("bots", [])}
        statuses = {row["bot_id"]: row for row in dashboard.get("runtime_statuses", [])}
        attachments = {row["bot_id"]: row for row in dashboard.get("active_match_attachments", [])}
        rows: list[dict] = []
        for side_key in ("team_a_id", "team_b_id"):
            team = teams.get(match.get(side_key), {"team_id": match.get(side_key), "name": "TBD", "bot_ids": [], "roles": {}})
            for bot_id in list(team.get("bot_ids", [])):
                rows.append(
                    {
                        "team_id": team.get("team_id"),
                        "team_name": team.get("name"),
                        "bot_id": bot_id,
                        "bot_name": (bots.get(bot_id) or {}).get("display_name", bot_id),
                        "role": (team.get("roles") or {}).get(bot_id),
                        "status": statuses.get(bot_id, {}),
                        "attachment": attachments.get(bot_id),
                    }
                )
        return rows

    def _available_instance_values(self, bot_id: str, attached_by_bot: dict[str, dict]) -> list[str]:
        current_attachment = attached_by_bot.get(bot_id)
        values: list[str] = []
        used_serials = {
            row["instance_serial"]
            for other_bot, row in attached_by_bot.items()
            if other_bot != bot_id and row.get("instance_serial")
        }
        for item in self.instance_rows.values():
            serial = item["serial"]
            if serial in used_serials:
                continue
            label = f"{item.get('display_label') or serial} [{serial}]"
            values.append(label)
        if current_attachment:
            label = f"{current_attachment.get('instance_label') or current_attachment.get('instance_serial')} [{current_attachment.get('instance_serial')}]"
            if label and label not in values:
                values.insert(0, label)
        return values

    def _attach_bot(self, match_id: str, bot_id: str) -> None:
        choice = self.attachment_vars.get(bot_id)
        if not choice:
            return
        instance = self.instance_rows.get(choice.get())
        if not instance:
            messagebox.showerror("Attach Runtime", "Select a detected live instance first.")
            return
        self.app.run_api_post(
            "/api/matches/runtime/attach",
            {
                "match_id": match_id,
                "bot_id": bot_id,
                "instance_serial": instance["serial"],
                "instance_label": instance.get("display_label"),
                "vendor": instance.get("vendor"),
                "model": instance.get("model"),
                "port": instance.get("port"),
                "match_confidence": instance.get("match_confidence"),
                "metadata": instance,
                "attached_by": "hub_operator",
            },
            label=f"attach_runtime:{bot_id}",
            error_title="Attach Runtime",
            on_success=lambda _result, b=bot_id: self.pending_attachment_choices.pop(b, None),
        )

    def _detach_bot(self, match_id: str, bot_id: str) -> None:
        self.app.run_api_post(
            "/api/matches/runtime/detach",
            {"match_id": match_id, "bot_id": bot_id},
            label=f"detach_runtime:{bot_id}",
            error_title="Detach Runtime",
            on_success=lambda _result, b=bot_id: self.pending_attachment_choices.pop(b, None),
        )

    def _remember_attachment_choice(self, bot_id: str, var: tk.StringVar) -> None:
        value = var.get().strip()
        if value:
            self.pending_attachment_choices[bot_id] = value
        else:
            self.pending_attachment_choices.pop(bot_id, None)

    def refresh(self, dashboard: dict) -> None:
        current_match = dashboard.get("current_match") or {}
        match_id = current_match.get("match_id")
        if not self._detected_instances and not self._instances_scan_inflight:
            self._instances_scan_inflight = True
            self.app.run_background_task(
                "tournament_instances_scan",
                lambda: {"ok": True, "instances": resolve_instances_cached(force=False)},
                on_success=self._apply_detected_instances,
                refresh_after=False,
                announce=False,
                surface_failure=False,
            )
        instances = self._detected_instances
        self.instance_rows = {
            f"{item.get('display_label') or item['serial']} [{item['serial']}]": item
            for item in instances
        }
        signature = (
            match_id,
            tuple((row.get("team_id"), row.get("name"), tuple(row.get("bot_ids", []))) for row in dashboard.get("teams", [])),
            tuple((row.get("bot_id"), row.get("process_state"), row.get("workflow_state"), row.get("selected_brawler")) for row in dashboard.get("runtime_statuses", [])),
            tuple((row.get("bot_id"), row.get("instance_serial")) for row in dashboard.get("active_match_attachments", [])),
            tuple(sorted(self.instance_rows.keys())),
            tuple((blocker.get("code"), blocker.get("bot_id"), blocker.get("message")) for blocker in dashboard.get("blockers", [])),
        )
        if signature == self._last_signature and self.body.winfo_children():
            return
        self._last_signature = signature

        for child in self.body.winfo_children():
            child.destroy()

        BracketView(self.body, dashboard.get("tournament"), []).pack(fill="x", expand=False)

        ModeMapSummary(
            self.body,
            mode_id=current_match.get("mode"),
            map_name=current_match.get("map_name"),
            title="Active Match Configuration",
        ).pack(fill="x", expand=False, pady=(16, 0))

        runtime_frame = tk.LabelFrame(
            self.body,
            text="Active Match Runtime Slice",
            bg="#17181b",
            fg="#f5efe8",
            font=("Segoe UI", 12, "bold"),
            padx=12,
            pady=12,
        )
        runtime_frame.pack(fill="x", expand=False, pady=(16, 0))

        if not match_id:
            tk.Label(
                runtime_frame,
                text="No active match selected yet. Tournament roster can exist without any live runtime attachments.",
                bg="#17181b",
                fg="#bcb5ae",
                font=("Segoe UI", 10),
            ).pack(anchor="w")
            return

        attachments = {row["bot_id"]: row for row in dashboard.get("active_match_attachments", [])}
        rows = self._match_bot_rows(dashboard)
        attached_count = len(attachments)

        tk.Label(
            runtime_frame,
            text=(
                f"Current active match: {match_id}  |  "
                f"Attached live instances: {attached_count} / {len(rows)}  |  "
                "Only these slots block preflight/start. Future teams may stay offline."
            ),
            bg="#17181b",
            fg="#bcb5ae",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(0, 10))

        header = tk.Frame(runtime_frame, bg="#17181b")
        header.pack(fill="x")
        for column, text, width in (
            (0, "Team / Bot Slot", 28),
            (1, "Attached Runtime", 34),
            (2, "Detected Live Instance", 38),
            (3, "State", 18),
            (4, "Pick", 16),
            (5, "Actions", 18),
        ):
            tk.Label(header, text=text, bg="#17181b", fg="#f5efe8", font=("Segoe UI", 9, "bold"), width=width, anchor="w").grid(row=0, column=column, padx=4, sticky="w")

        self.attachment_vars = {}
        for index, row in enumerate(rows, start=1):
            slot = tk.Frame(runtime_frame, bg="#202228")
            slot.pack(fill="x", pady=4)
            bot_id = row["bot_id"]
            attachment = row.get("attachment") or {}
            status = row.get("status") or {}
            label = f"{row['team_name']} / {row['bot_name']}"
            if row.get("role"):
                label += f" ({row['role']})"
            tk.Label(slot, text=label, bg="#202228", fg="#f5efe8", font=("Segoe UI", 10, "bold"), width=28, anchor="w").grid(row=0, column=0, padx=6, pady=6, sticky="w")

            attached_text = attachment.get("instance_label") or "<not attached>"
            tk.Label(slot, text=attached_text, bg="#202228", fg="#bcb5ae", font=("Segoe UI", 9), width=34, anchor="w").grid(row=0, column=1, padx=6, pady=6, sticky="w")

            values = self._available_instance_values(bot_id, attachments)
            pending_value = self.pending_attachment_choices.get(bot_id, "")
            current_value = (
                f"{attachment.get('instance_label') or attachment.get('instance_serial')} [{attachment.get('instance_serial')}]"
                if attachment
                else (pending_value if pending_value in values else (values[0] if values else ""))
            )
            var = tk.StringVar(value=current_value)
            self.attachment_vars[bot_id] = var
            combo = ttk.Combobox(slot, textvariable=var, values=values, width=44, state="readonly" if values else "disabled")
            combo.grid(row=0, column=2, padx=6, pady=6, sticky="w")
            combo.bind("<<ComboboxSelected>>", lambda _event, b=bot_id, v=var: self._remember_attachment_choice(b, v))

            state_text = f"{status.get('process_state', 'inactive')} / {status.get('workflow_state', 'not_ready')}"
            tk.Label(slot, text=state_text, bg="#202228", fg="#bcb5ae", font=("Consolas", 9), width=18, anchor="w").grid(row=0, column=3, padx=6, pady=6, sticky="w")
            tk.Label(slot, text=status.get("selected_brawler") or "-", bg="#202228", fg="#bcb5ae", font=("Segoe UI", 9), width=16, anchor="w").grid(row=0, column=4, padx=6, pady=6, sticky="w")

            actions = tk.Frame(slot, bg="#202228")
            actions.grid(row=0, column=5, padx=6, pady=6, sticky="w")
            tk.Button(actions, text="Attach", command=lambda b=bot_id: self._attach_bot(match_id, b), bg="#d2452d", fg="#f5efe8", relief="flat").pack(side="left")
            tk.Button(actions, text="Detach", command=lambda b=bot_id: self._detach_bot(match_id, b), bg="#30333a", fg="#f5efe8", relief="flat").pack(side="left", padx=(6, 0))

        detected_frame = tk.LabelFrame(
            self.body,
            text="Detected Live Instances",
            bg="#17181b",
            fg="#f5efe8",
            font=("Segoe UI", 12, "bold"),
            padx=12,
            pady=12,
        )
        detected_frame.pack(fill="x", expand=False, pady=(16, 0))
        if not instances:
            tk.Label(detected_frame, text="No live emulator instances detected right now.", bg="#17181b", fg="#bcb5ae", font=("Segoe UI", 10)).pack(anchor="w")
        else:
            for item in instances:
                line = (
                    f"{item.get('display_label') or item['serial']}  |  "
                    f"serial={item['serial']}  |  vendor={item.get('vendor', '-')}"
                )
                tk.Label(detected_frame, text=line, bg="#17181b", fg="#bcb5ae", font=("Consolas", 9), anchor="w", justify="left").pack(anchor="w", pady=2)

        BlockerList(self.body, dashboard.get("blockers", [])).pack(fill="x", pady=(16, 0))

    def _apply_detected_instances(self, result: dict) -> None:
        self._instances_scan_inflight = False
        self._detected_instances = result.get("instances", [])
        if self.app.current_page == "tournament":
            self.app.refresh_current_page(force=True)

    def _apply_setup_quick_match(self, result: dict) -> None:
        prefetched = result.get("prefetched_dashboard")
        if prefetched and prefetched.get("ok"):
            self.app.last_dashboard = prefetched
