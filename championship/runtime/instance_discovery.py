from __future__ import annotations

from typing import Any

from instance_identity import resolve_instances_cached


def detect_instances(current_port: int | None = None, *, force: bool = False) -> list[dict[str, Any]]:
    return resolve_instances_cached(current_port, force=force)
