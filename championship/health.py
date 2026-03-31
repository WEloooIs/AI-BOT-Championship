from __future__ import annotations

from datetime import UTC, datetime

from .models import ControlPlaneHealth


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def build_health(database_writable: bool, observer_healthy: bool, degraded_reasons: list[str]) -> ControlPlaneHealth:
    return ControlPlaneHealth(
        coordinator_alive=True,
        database_writable=database_writable,
        observer_healthy=observer_healthy,
        last_checked_at=utc_now(),
        degraded_reasons=degraded_reasons,
    )
