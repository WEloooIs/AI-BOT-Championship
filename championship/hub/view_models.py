from __future__ import annotations


def runtime_status_lookup(dashboard: dict) -> dict[str, dict]:
    return {row["bot_id"]: row for row in dashboard.get("runtime_statuses", [])}


def bots_lookup(dashboard: dict) -> dict[str, dict]:
    return {row["bot_id"]: row for row in dashboard.get("bots", [])}


def attachments_lookup(dashboard: dict) -> dict[str, dict]:
    return {row["bot_id"]: row for row in dashboard.get("active_match_attachments", [])}


def teams_lookup(dashboard: dict) -> dict[str, dict]:
    return {row["team_id"]: row for row in dashboard.get("teams", [])}


def current_match_teams(dashboard: dict) -> tuple[dict, dict]:
    match = dashboard.get("current_match") or {}
    teams = teams_lookup(dashboard)
    left = teams.get(match.get("team_a_id"), {"team_id": "", "name": "Team A", "bot_ids": [], "roles": {}})
    right = teams.get(match.get("team_b_id"), {"team_id": "", "name": "Team B", "bot_ids": [], "roles": {}})
    return left, right
