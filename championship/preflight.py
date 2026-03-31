from __future__ import annotations

from championship.enums import BlockerSeverity, BotProcessState, PickLifecycleState
from championship.error_codes import (
    BOT_NOT_ATTACHED_TO_ACTIVE_MATCH,
    BOT_NOT_READY,
    BOT_RUNTIME_MISSING_FOR_ACTIVE_MATCH,
    BOT_UNRESPONSIVE,
    BRACKET_STAGE_INVALID,
    LOADOUT_NOT_CONFIRMED,
    LOADOUT_VERIFIED_PARTIAL,
    MAP_NOT_SELECTED,
    MODE_NOT_SELECTED,
    OBSERVER_NOT_READY,
    PICK_NOT_CONFIRMED,
    TEAM_INCOMPLETE,
)
from championship.loadout_state import (
    is_loadout_ready,
    loadout_result_for_assignment,
    loadout_state_for_assignment,
    loadout_warning_state,
    pick_requires_loadout,
)
from championship.models import MatchStartBlocker
from championship.runtime.ready_validator import is_runtime_ready


def derive_match_start_blockers(
    *,
    match_context_version: int,
    mode: str | None,
    map_name: str | None,
    observer_ready: bool,
    teams: list[dict],
    runtime_statuses: dict[str, dict],
    runtime_attachments: dict[str, dict],
    pick_assignments: dict[str, dict],
    stage_valid: bool,
) -> list[MatchStartBlocker]:
    blockers: list[MatchStartBlocker] = []

    if not stage_valid:
        blockers.append(
            MatchStartBlocker(
                code=BRACKET_STAGE_INVALID,
                severity=BlockerSeverity.ERROR,
                message="Current tournament stage does not allow match start.",
                recoverable=True,
                suggested_action="Verify active match and bracket stage.",
            )
        )
    if not mode:
        blockers.append(
            MatchStartBlocker(
                code=MODE_NOT_SELECTED,
                severity=BlockerSeverity.ERROR,
                message="Match mode is not selected.",
                recoverable=True,
                suggested_action="Select a mode for the active match.",
            )
        )
    if not map_name:
        blockers.append(
            MatchStartBlocker(
                code=MAP_NOT_SELECTED,
                severity=BlockerSeverity.ERROR,
                message="Match map is not selected.",
                recoverable=True,
                suggested_action="Select a map for the active match.",
            )
        )
    if not observer_ready:
        blockers.append(
            MatchStartBlocker(
                code=OBSERVER_NOT_READY,
                severity=BlockerSeverity.WARNING,
                message="Observer subsystem is not healthy.",
                recoverable=True,
                suggested_action="Check observer and coordinator health.",
            )
        )

    for team in teams:
        bot_ids = list(team.get("bot_ids", []))
        if len(bot_ids) != 3:
            blockers.append(
                MatchStartBlocker(
                    code=TEAM_INCOMPLETE,
                    severity=BlockerSeverity.ERROR,
                    message=f"Team {team['name']} does not have 3 assigned bots.",
                    team_id=team["team_id"],
                    recoverable=True,
                    suggested_action="Assign 3 bots to the team.",
                )
            )

        for bot_id in bot_ids:
            runtime = runtime_statuses.get(bot_id, {})
            attachment = runtime_attachments.get(bot_id)
            assignment = pick_assignments.get(bot_id)

            if not attachment:
                blockers.append(
                    MatchStartBlocker(
                        code=BOT_NOT_ATTACHED_TO_ACTIVE_MATCH,
                        severity=BlockerSeverity.ERROR,
                        message=f"Bot {bot_id} is not attached to the current active match runtime.",
                        bot_id=bot_id,
                        team_id=team["team_id"],
                        recoverable=True,
                        suggested_action="Attach a live emulator instance to this logical bot slot.",
                    )
                )

            if runtime.get("process_state") in {
                BotProcessState.UNRESPONSIVE,
                BotProcessState.CRASHED,
                BotProcessState.ERROR,
            } and attachment:
                blockers.append(
                    MatchStartBlocker(
                        code=BOT_UNRESPONSIVE,
                        severity=BlockerSeverity.ERROR,
                        message=f"Bot {bot_id} is not responding.",
                        bot_id=bot_id,
                        team_id=team["team_id"],
                        recoverable=True,
                        suggested_action="Relaunch the bot worker or run recovery.",
                    )
                )

            if not assignment or int(assignment.get("match_context_version", -1)) != match_context_version:
                blockers.append(
                    MatchStartBlocker(
                        code=PICK_NOT_CONFIRMED,
                        severity=BlockerSeverity.ERROR,
                        message=f"Bot {bot_id} has no current pick assignment.",
                        bot_id=bot_id,
                        team_id=team["team_id"],
                        recoverable=True,
                        suggested_action="Regenerate the draft for the current match context.",
                    )
                )
                continue

            if attachment and runtime.get("process_state") not in {
                BotProcessState.ACTIVE,
                BotProcessState.STALE,
            }:
                blockers.append(
                    MatchStartBlocker(
                        code=BOT_RUNTIME_MISSING_FOR_ACTIVE_MATCH,
                        severity=BlockerSeverity.ERROR,
                        message=f"Bot {bot_id} has no live runtime for the current active match attachment.",
                        bot_id=bot_id,
                        team_id=team["team_id"],
                        recoverable=True,
                        suggested_action="Launch or relaunch the worker for the attached emulator instance.",
                    )
                )
                continue

            if assignment.get("state") != PickLifecycleState.CONFIRMED:
                detail = assignment.get("failure_code") or assignment.get("state") or "pending"
                blockers.append(
                    MatchStartBlocker(
                        code=PICK_NOT_CONFIRMED,
                        severity=BlockerSeverity.ERROR,
                        message=f"Bot {bot_id} has not confirmed pick yet ({detail}).",
                        bot_id=bot_id,
                        team_id=team["team_id"],
                        recoverable=True,
                        suggested_action="Wait for pick confirmation or relaunch recovery.",
                    )
                )

            if assignment.get("state") == PickLifecycleState.CONFIRMED and not is_loadout_ready(assignment):
                loadout_result = loadout_result_for_assignment(assignment)
                failure_code = (
                    loadout_result.get("error_code")
                    or assignment.get("failure_code")
                    or LOADOUT_NOT_CONFIRMED
                )
                blockers.append(
                    MatchStartBlocker(
                        code=failure_code,
                        severity=BlockerSeverity.ERROR,
                        message=(
                            f"Bot {bot_id} has not confirmed requested loadout yet "
                            f"({loadout_state_for_assignment(assignment)})."
                        ),
                        bot_id=bot_id,
                        team_id=team["team_id"],
                        recoverable=True,
                        suggested_action="Retry the pick package or inspect loadout automation diagnostics.",
                    )
                )

            if assignment.get("state") == PickLifecycleState.CONFIRMED and loadout_warning_state(assignment):
                loadout_result = loadout_result_for_assignment(assignment)
                blockers.append(
                    MatchStartBlocker(
                        code=LOADOUT_VERIFIED_PARTIAL,
                        severity=BlockerSeverity.WARNING,
                        message=(
                            f"Bot {bot_id} only has partial/best-effort loadout verification "
                            f"({loadout_state_for_assignment(assignment)})."
                        ),
                        bot_id=bot_id,
                        team_id=team["team_id"],
                        recoverable=True,
                        suggested_action=(
                            loadout_result.get("degraded_reason")
                            or "Inspect loadout logs if strict build verification is required."
                        ),
                    )
                )

            if attachment and not is_runtime_ready(runtime, match_context_version):
                blockers.append(
                    MatchStartBlocker(
                        code=BOT_NOT_READY,
                        severity=BlockerSeverity.ERROR,
                        message=f"Bot {bot_id} did not pass derived readiness checks.",
                        bot_id=bot_id,
                        team_id=team["team_id"],
                        recoverable=True,
                        suggested_action="Check heartbeat, workflow state, and match context version.",
                    )
                )

    return blockers
