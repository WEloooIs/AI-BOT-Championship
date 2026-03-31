from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    return datetime.now(UTC)


def is_message_fresh(message: dict) -> bool:
    created = datetime.fromisoformat(message["timestamp"])
    ttl = timedelta(milliseconds=int(message.get("ttl_ms", 0)))
    return utc_now() <= created + ttl
