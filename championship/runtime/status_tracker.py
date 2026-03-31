from __future__ import annotations

from datetime import UTC, datetime, timedelta

from championship.enums import BotProcessState


def classify_process_state(last_heartbeat_at: str | None, has_process: bool) -> str:
    if not has_process and not last_heartbeat_at:
        return BotProcessState.INACTIVE
    if not last_heartbeat_at:
        return BotProcessState.LAUNCHING if has_process else BotProcessState.INACTIVE
    seen = datetime.fromisoformat(last_heartbeat_at)
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    age = datetime.now(UTC) - seen
    if age <= timedelta(seconds=5):
        return BotProcessState.ACTIVE
    if age <= timedelta(seconds=15):
        return BotProcessState.STALE
    return BotProcessState.UNRESPONSIVE if has_process else BotProcessState.CRASHED
