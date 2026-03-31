from __future__ import annotations

from championship.tournament.bracket_engine import build_semifinal_pairs


class TournamentManager:
    def build_initial_pairings(self, team_ids: list[str]) -> list[tuple[str, str, str]]:
        return build_semifinal_pairs(team_ids)
