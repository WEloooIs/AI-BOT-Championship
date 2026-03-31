from __future__ import annotations

from championship.platform.base import FriendlyBattleSnapshot, PlatformAdapter
from championship.platform.nulls import NULLS_PLATFORM
from championship.platform.official import OFFICIAL_PLATFORM


PLATFORM_REGISTRY: dict[str, PlatformAdapter] = {
    OFFICIAL_PLATFORM.name: OFFICIAL_PLATFORM,
    NULLS_PLATFORM.name: NULLS_PLATFORM,
}


def get_platform_adapter(name: str | None) -> PlatformAdapter:
    if not name:
        return NULLS_PLATFORM
    return PLATFORM_REGISTRY.get(str(name).lower(), NULLS_PLATFORM)


__all__ = [
    "FriendlyBattleSnapshot",
    "PlatformAdapter",
    "NULLS_PLATFORM",
    "OFFICIAL_PLATFORM",
    "get_platform_adapter",
]
