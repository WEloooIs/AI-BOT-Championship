from __future__ import annotations

import json
import tkinter as tk


class HandshakePanel(tk.LabelFrame):
    def __init__(self, master, handshake: dict | None) -> None:
        super().__init__(master, text="Handshake Diagnostics", bg="#17181b", fg="#f5efe8", font=("Segoe UI", 12, "bold"))
        self.body = tk.Frame(self, bg="#17181b")
        self.body.pack(fill="x", expand=True)
        self._last_signature = None
        self.refresh(handshake)

    def refresh(self, handshake: dict | None) -> None:
        handshake = handshake or {}
        signature = json.dumps(handshake, ensure_ascii=False, sort_keys=True)
        if signature == self._last_signature:
            return
        self._last_signature = signature
        for child in self.body.winfo_children():
            child.destroy()
        if not handshake:
            tk.Label(
                self.body,
                text="No active handshake diagnostics yet.",
                bg="#17181b",
                fg="#bcb5ae",
                font=("Segoe UI", 10),
            ).pack(anchor="w", padx=12, pady=10)
            return

        summary = tk.Frame(self.body, bg="#17181b")
        summary.pack(fill="x", padx=12, pady=(12, 6))
        summary_text = (
            f"phase: {handshake.get('phase', '-')}\n"
            f"match_status: {handshake.get('match_status', '-')}\n"
            f"current_host: {handshake.get('current_host_bot_id') or '-'}\n"
            f"default_host: {handshake.get('default_host_bot_id') or '-'}\n"
            f"host_failover_active: {'yes' if handshake.get('host_failover_active') else 'no'}"
        )
        tk.Label(summary, text=summary_text, justify="left", anchor="w", bg="#17181b", fg="#f5efe8", font=("Consolas", 10)).pack(side="left")

        steps = tk.Frame(self.body, bg="#17181b")
        steps.pack(fill="x", padx=12, pady=(0, 10))
        for step in handshake.get("steps", []):
            color = "#9fd8b5" if step.get("status") == "ok" else "#f0c4b5"
            tk.Label(
                steps,
                text=f"{step.get('label')}: {step.get('value')}",
                bg="#202228",
                fg=color,
                font=("Segoe UI", 9, "bold"),
                padx=10,
                pady=6,
            ).pack(side="left", padx=(0, 8))

        bots_frame = tk.Frame(self.body, bg="#17181b")
        bots_frame.pack(fill="x", padx=12, pady=(0, 10))
        for bot in handshake.get("bots", []):
            seen = bot.get("snapshot", {}) or {}
            missing = ", ".join(bot.get("missing", [])) or "-"
            attachment = (bot.get("attachment") or {}).get("instance_label") or "<detached>"
            bot_text = (
                f"{bot.get('bot_id')}  "
                f"[host={'yes' if bot.get('is_host') else 'no'}]  "
                f"attach={attachment}  "
                f"proc={bot.get('process_state')}  "
                f"flow={bot.get('workflow_state')}  "
                f"pick={bot.get('pick_state') or '-'}  "
                f"step={bot.get('handshake_step')}  "
                f"base={seen.get('base_state', '-')}  "
                f"snapshot_flow={seen.get('workflow_state', '-')}  "
                f"missing={missing}"
            )
            if bot.get("last_error_code"):
                bot_text += f"  error={bot.get('last_error_code')}"
            tk.Label(
                bots_frame,
                text=bot_text,
                justify="left",
                anchor="w",
                bg="#202228",
                fg="#f5efe8",
                wraplength=1450,
                font=("Consolas", 9),
                padx=8,
                pady=6,
            ).pack(fill="x", pady=3)

        events = handshake.get("recent_events", [])
        if events:
            events_frame = tk.Frame(self.body, bg="#17181b")
            events_frame.pack(fill="x", padx=12, pady=(0, 12))
            tk.Label(events_frame, text="Recent match events", bg="#17181b", fg="#bcb5ae", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
            for event in events[:8]:
                line = f"{event.get('timestamp')}  {event.get('event_type')}  {event.get('error_code') or '-'}"
                tk.Label(
                    events_frame,
                    text=line,
                    justify="left",
                    anchor="w",
                    bg="#17181b",
                    fg="#bcb5ae",
                    font=("Consolas", 9),
                ).pack(anchor="w")
