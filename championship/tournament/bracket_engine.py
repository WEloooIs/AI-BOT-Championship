from __future__ import annotations

from championship.enums import MatchStage


DEFAULT_STAGE_ORDER = [MatchStage.SEMIFINAL_1, MatchStage.SEMIFINAL_2, MatchStage.FINAL]


def build_semifinal_pairs(team_ids: list[str]) -> list[tuple[str, str, str]]:
    if len(team_ids) != 4:
        raise ValueError("Bracket engine requires exactly 4 teams for the MVP format.")
    return [
        (MatchStage.SEMIFINAL_1, team_ids[0], team_ids[1]),
        (MatchStage.SEMIFINAL_2, team_ids[2], team_ids[3]),
    ]
