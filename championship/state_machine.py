from __future__ import annotations

from .enums import TournamentState


ALLOWED_TOURNAMENT_TRANSITIONS: dict[str, set[str]] = {
    TournamentState.IDLE: {TournamentState.DRAFTING},
    TournamentState.DRAFTING: {TournamentState.WAITING_BOTS, TournamentState.ERROR_RECOVERY},
    TournamentState.WAITING_BOTS: {TournamentState.READY_CHECK, TournamentState.ERROR_RECOVERY},
    TournamentState.READY_CHECK: {TournamentState.LOBBY_SETUP, TournamentState.ERROR_RECOVERY},
    TournamentState.LOBBY_SETUP: {TournamentState.MATCH_STARTING, TournamentState.ERROR_RECOVERY},
    TournamentState.MATCH_STARTING: {TournamentState.IN_MATCH, TournamentState.ERROR_RECOVERY},
    TournamentState.IN_MATCH: {TournamentState.MATCH_FINISHED, TournamentState.ERROR_RECOVERY},
    TournamentState.MATCH_FINISHED: {TournamentState.REPORT_BUILDING, TournamentState.ERROR_RECOVERY},
    TournamentState.REPORT_BUILDING: {TournamentState.ADVANCE_BRACKET, TournamentState.ERROR_RECOVERY},
    TournamentState.ADVANCE_BRACKET: {
        TournamentState.DRAFTING,
        TournamentState.TOURNAMENT_FINISHED,
        TournamentState.ERROR_RECOVERY,
    },
    TournamentState.ERROR_RECOVERY: {
        TournamentState.WAITING_BOTS,
        TournamentState.READY_CHECK,
        TournamentState.ADVANCE_BRACKET,
        TournamentState.TOURNAMENT_FINISHED,
    },
    TournamentState.TOURNAMENT_FINISHED: set(),
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TOURNAMENT_TRANSITIONS.get(current, set())
