from __future__ import annotations

import tkinter as tk

from championship.hub.widgets.bot_slot import BotSlot


class TeamPanel(tk.LabelFrame):
    def __init__(
        self,
        master,
        team: dict,
        runtime_lookup: dict[str, dict],
        bot_lookup: dict[str, dict] | None = None,
        attachments_lookup: dict[str, dict] | None = None,
    ) -> None:
        super().__init__(
            master,
            text=team.get("name", "Team"),
            bg="#17181b",
            fg="#f5efe8",
            bd=1,
            highlightthickness=1,
            highlightbackground=team.get("color", "#31333a"),
            font=("Segoe UI", 12, "bold"),
            padx=10,
            pady=10,
        )
        self.slots = tk.Frame(self, bg="#17181b")
        self.slots.pack(fill="both", expand=True)
        self.slot_widgets: dict[str, BotSlot] = {}
        self.refresh(team, runtime_lookup, bot_lookup, attachments_lookup)

    def refresh(
        self,
        team: dict,
        runtime_lookup: dict[str, dict],
        bot_lookup: dict[str, dict] | None = None,
        attachments_lookup: dict[str, dict] | None = None,
    ) -> None:
        self.configure(text=team.get("name", "Team"), highlightbackground=team.get("color", "#31333a"))
        bot_lookup = bot_lookup or {}
        attachments_lookup = attachments_lookup or {}
        active_bot_ids = list(team.get("bot_ids", []))
        for bot_id in list(self.slot_widgets):
            if bot_id not in active_bot_ids:
                self.slot_widgets.pop(bot_id).destroy()
        for index, bot_id in enumerate(active_bot_ids):
            status = runtime_lookup.get(bot_id, {})
            bot = bot_lookup.get(bot_id, {})
            attachment = attachments_lookup.get(bot_id, {})
            subtitle = attachment.get("instance_label") or bot.get("instance_id") or status.get("instance_id") or team.get("team_id", "")
            slot = self.slot_widgets.get(bot_id)
            if slot is None:
                slot = BotSlot(
                    self.slots,
                    title=bot.get("display_name", bot_id),
                    subtitle=subtitle,
                    process_state=status.get("process_state", "inactive"),
                    workflow_state=status.get("workflow_state", "not_ready"),
                    brawler=status.get("selected_brawler"),
                    role=team.get("roles", {}).get(bot_id),
                )
                self.slot_widgets[bot_id] = slot
            else:
                slot.update_slot(
                    title=bot.get("display_name", bot_id),
                    subtitle=subtitle,
                    process_state=status.get("process_state", "inactive"),
                    workflow_state=status.get("workflow_state", "not_ready"),
                    brawler=status.get("selected_brawler"),
                    role=team.get("roles", {}).get(bot_id),
                )
            slot.grid(row=index, column=0, pady=6, sticky="ew")
        self.slots.grid_columnconfigure(0, weight=1)
