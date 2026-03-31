from __future__ import annotations

from enum import StrEnum


class TournamentState(StrEnum):
    IDLE = "idle"
    DRAFTING = "drafting"
    WAITING_BOTS = "waiting_bots"
    READY_CHECK = "ready_check"
    LOBBY_SETUP = "lobby_setup"
    MATCH_STARTING = "match_starting"
    IN_MATCH = "in_match"
    MATCH_FINISHED = "match_finished"
    REPORT_BUILDING = "report_building"
    ADVANCE_BRACKET = "advance_bracket"
    TOURNAMENT_FINISHED = "tournament_finished"
    ERROR_RECOVERY = "error_recovery"


class PickLifecycleState(StrEnum):
    ASSIGNED = "pick_assigned"
    IN_PROGRESS = "pick_in_progress"
    CONFIRMED = "pick_confirmed"
    FAILED = "pick_failed"


class LoadoutLifecycleState(StrEnum):
    NOT_REQUESTED = "loadout_not_requested"
    APPLYING = "loadout_applying"
    APPLIED_BEST_EFFORT = "loadout_applied_best_effort"
    VERIFIED_PARTIAL = "loadout_verified_partial"
    VERIFIED_FULL = "loadout_verified_full"
    FAILED = "loadout_failed"


class CommandLifecycleState(StrEnum):
    ISSUED = "command_issued"
    ACCEPTED = "command_accepted"
    COMPLETED = "command_completed"
    FAILED = "command_failed"


class BotProcessState(StrEnum):
    INACTIVE = "inactive"
    LAUNCHING = "launching"
    ACTIVE = "active"
    STALE = "stale"
    UNRESPONSIVE = "unresponsive"
    CRASHED = "crashed"
    ERROR = "error"


class BotWorkflowState(StrEnum):
    NOT_READY = "not_ready"
    SELECTING_BRAWLER = "selecting_brawler"
    BRAWLER_SELECTED = "brawler_selected"
    IN_LOBBY = "in_lobby"
    MATCHMAKING = "matchmaking"
    IN_MATCH = "in_match"
    POST_MATCH = "post_match"


class BlockerSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class TeamRole(StrEnum):
    AGGRO = "aggro"
    SUPPORT = "support"
    ANCHOR = "anchor"
    OBJECTIVE = "objective"
    FLEX = "flex"


class MessageType(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    TARGET_CALL = "TARGET_CALL"
    OBJECTIVE_CALL = "OBJECTIVE_CALL"
    POSITION_CALL = "POSITION_CALL"
    STATE_CHANGE = "STATE_CHANGE"
    SUPPORT_REQUEST = "SUPPORT_REQUEST"
    OBSERVER_NOTE = "OBSERVER_NOTE"
    HIGHLIGHT_EVENT = "HIGHLIGHT_EVENT"


class MatchStage(StrEnum):
    EXHIBITION = "exhibition"
    SEMIFINAL_1 = "semifinal_1"
    SEMIFINAL_2 = "semifinal_2"
    FINAL = "final"


class MatchStatus(StrEnum):
    PENDING = "pending"
    DRAFTING = "drafting"
    READY_CHECK = "ready_check"
    LOBBY_SETUP = "lobby_setup"
    STARTING = "match_starting"
    IN_MATCH = "in_match"
    FINISHED = "match_finished"
    FAILED = "failed"


class PlatformType(StrEnum):
    OFFICIAL = "official"
    NULLS = "nulls"
