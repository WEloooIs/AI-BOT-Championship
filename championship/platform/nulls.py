from __future__ import annotations

from championship.platform.base import PlatformAdapter


NULLS_PLATFORM = PlatformAdapter(
    name="nulls",
    friendly_keywords=(
        "friendly",
        "friendly battle",
        "team code",
        "custom",
        "room",
        "nulls",
    ),
    start_button_keywords=("play", "ready"),
    matchmaking_keywords=("exit", "cancel", "searching", "finding"),
    queue_exit_keywords=("exit", "cancel"),
    require_explicit_friendly_text=False,
)
