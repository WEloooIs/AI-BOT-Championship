from __future__ import annotations


def build_match_package(match_row: dict, draft_row: dict | None, teams: list[dict]) -> dict:
    return {
        "match_id": match_row["match_id"],
        "tournament_id": match_row["tournament_id"],
        "stage": match_row["stage"],
        "mode": match_row.get("mode"),
        "map": match_row.get("map_name"),
        "match_context_version": int(match_row["match_context_version"]),
        "teams": teams,
        "draft": draft_row or {},
    }
