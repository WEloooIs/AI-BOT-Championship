from __future__ import annotations

from championship.teams.team_registry import TeamRegistry


class PartyManager:
    def __init__(self) -> None:
        self.registry = TeamRegistry()

    def normalize_bot_ids(self, bot_ids: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for bot_id in bot_ids:
            if bot_id and bot_id not in seen:
                ordered.append(bot_id)
                seen.add(bot_id)
        return ordered[: self.registry.max_team_size]
