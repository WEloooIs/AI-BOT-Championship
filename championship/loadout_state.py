from __future__ import annotations

from typing import Any

from championship.enums import LoadoutLifecycleState


READY_LOADOUT_STATES = {
    LoadoutLifecycleState.NOT_REQUESTED,
    LoadoutLifecycleState.APPLIED_BEST_EFFORT,
    LoadoutLifecycleState.VERIFIED_PARTIAL,
    LoadoutLifecycleState.VERIFIED_FULL,
}


def pick_requires_loadout(assignment: dict[str, Any] | None) -> bool:
    if not assignment:
        return False
    pick_package = assignment.get("pick_package") or {}
    loadout = pick_package.get("loadout") or {}
    return bool(loadout)


def loadout_state_for_assignment(assignment: dict[str, Any] | None) -> str:
    if not assignment:
        return str(LoadoutLifecycleState.NOT_REQUESTED)
    return str(assignment.get("loadout_state") or LoadoutLifecycleState.NOT_REQUESTED)


def loadout_result_for_assignment(assignment: dict[str, Any] | None) -> dict[str, Any]:
    if not assignment:
        return {}
    result = assignment.get("loadout_result") or {}
    return result if isinstance(result, dict) else {}


def is_loadout_ready(assignment: dict[str, Any] | None) -> bool:
    state = loadout_state_for_assignment(assignment)
    if state not in READY_LOADOUT_STATES:
        return False
    if not pick_requires_loadout(assignment):
        return True
    if state == LoadoutLifecycleState.VERIFIED_FULL:
        return True
    if state in {
        LoadoutLifecycleState.APPLIED_BEST_EFFORT,
        LoadoutLifecycleState.VERIFIED_PARTIAL,
    }:
        return bool(loadout_result_for_assignment(assignment))
    return False


def loadout_warning_state(assignment: dict[str, Any] | None) -> bool:
    if not pick_requires_loadout(assignment):
        return False
    return loadout_state_for_assignment(assignment) in {
        LoadoutLifecycleState.APPLIED_BEST_EFFORT,
        LoadoutLifecycleState.VERIFIED_PARTIAL,
    }
