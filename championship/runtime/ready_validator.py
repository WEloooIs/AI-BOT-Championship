from __future__ import annotations


def is_runtime_ready(runtime_status: dict, expected_version: int) -> bool:
    return (
        bool(runtime_status.get("responsive"))
        and int(runtime_status.get("match_context_version", -1)) == expected_version
        and runtime_status.get("workflow_state") in {"brawler_selected", "in_lobby", "matchmaking", "in_match"}
        and not runtime_status.get("last_error_code")
    )
