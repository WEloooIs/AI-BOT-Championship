from __future__ import annotations

from championship.observer.highlight_selector import select_highlights
from championship.observer.mvp_scoring import score_match
from championship.observer.narrative_builder import build_narrative
from championship.observer.report_builder import build_report
from championship.observer.timeline_builder import build_timeline


class ObserverService:
    def __init__(self) -> None:
        self.healthy = True

    def build_match_outputs(
        self,
        *,
        match_row: dict,
        draft_row: dict | None,
        notes: list[dict],
        messages: list[dict],
        overrides: list[dict],
        bot_ids: list[str],
    ) -> dict:
        timeline = build_timeline(
            match_row["match_id"],
            int(match_row["match_context_version"]),
            messages,
            notes,
        )
        highlights = select_highlights(timeline)
        mvp_scores = score_match(bot_ids)
        narrative = build_narrative(match_row, highlights)
        report = build_report(
            match_row=match_row,
            draft_row=draft_row,
            notes=notes,
            highlights=highlights,
            mvp_scores=mvp_scores,
            narrative_summary=narrative,
            overrides=overrides,
        )
        return {
            "timeline": timeline,
            "highlights": highlights,
            "mvp_scores": mvp_scores,
            "report": report,
            "narrative": narrative,
        }
