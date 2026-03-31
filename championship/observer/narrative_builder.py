from __future__ import annotations


def build_narrative(match_row: dict, highlights: list[dict]) -> str:
    winner = match_row.get("winner_team_id") or "unknown winner"
    if highlights:
        return f"Матч завершён в пользу {winner}. Ключевой импульс пришёл через {highlights[0]['short_title'].lower()}."
    return f"Матч завершён в пользу {winner}. Narrative v1 собран по rule-based timeline."
