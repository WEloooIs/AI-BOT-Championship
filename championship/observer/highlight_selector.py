from __future__ import annotations


def select_highlights(timeline: list[dict]) -> list[dict]:
    candidates = []
    for index, event in enumerate(timeline[:3]):
        candidates.append(
            {
                "rank": index + 1,
                "event_type": event["event_type"],
                "short_title": event["event_type"].replace("_", " ").title(),
                "short_summary": "Rule-based highlight candidate generated from the active match timeline.",
            }
        )
    return candidates
