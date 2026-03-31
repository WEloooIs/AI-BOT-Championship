from __future__ import annotations

from championship.models import MatchReport


def build_report(
    *,
    match_row: dict,
    draft_row: dict | None,
    notes: list[dict],
    highlights: list[dict],
    mvp_scores: list[dict],
    narrative_summary: str,
    overrides: list[dict],
) -> MatchReport:
    mvp_bot = None
    if mvp_scores:
        mvp_bot = sorted(mvp_scores, key=lambda item: item["total_score"], reverse=True)[0]["bot_id"]
    return MatchReport(
        match_id=match_row["match_id"],
        tournament_id=match_row["tournament_id"],
        match_context_version=int(match_row["match_context_version"]),
        stage=match_row["stage"],
        mode=match_row.get("mode"),
        map_name=match_row.get("map_name"),
        draft_a=(draft_row or {}).get("team_a_final", []),
        draft_b=(draft_row or {}).get("team_b_final", []),
        draft_a_packages=(draft_row or {}).get("team_a_packages", []),
        draft_b_packages=(draft_row or {}).get("team_b_packages", []),
        winner=match_row.get("winner_team_id"),
        mvp_bot_id=mvp_bot,
        duration_sec=0.0,
        key_moment=highlights[0]["short_title"] if highlights else None,
        tactical_summary="Hybrid rule-based observer report generated from runtime and match lifecycle events.",
        observer_notes=notes,
        top_moments=highlights,
        narrative_summary=narrative_summary,
        manual_overrides=overrides,
    )
