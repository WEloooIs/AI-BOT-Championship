from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def build_timeline(match_id: str, version: int, messages: list[dict], notes: list[dict]) -> list[dict]:
    timeline = [
        {
            "timestamp": utc_now(),
            "match_id": match_id,
            "match_context_version": version,
            "event_type": "match_timeline_snapshot",
            "payload": {"message_count": len(messages), "note_count": len(notes)},
        }
    ]
    timeline.extend(
        {
            "timestamp": item["timestamp"],
            "match_id": match_id,
            "match_context_version": version,
            "event_type": item.get("signal", "bus_event"),
            "payload": item.get("payload", {}),
        }
        for item in messages
    )
    return timeline
