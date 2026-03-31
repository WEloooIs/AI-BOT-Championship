from __future__ import annotations

from championship.enums import TeamRole


DEFAULT_ROLE_ROTATION = [TeamRole.AGGRO, TeamRole.SUPPORT, TeamRole.ANCHOR]


def default_roles(bot_ids: list[str]) -> dict[str, str]:
    roles: dict[str, str] = {}
    for index, bot_id in enumerate(bot_ids):
        roles[bot_id] = DEFAULT_ROLE_ROTATION[min(index, len(DEFAULT_ROLE_ROTATION) - 1)]
    return roles
