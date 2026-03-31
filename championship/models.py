from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


def to_plain_dict(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_plain_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_dict(item) for key, item in value.items()}
    return value


@dataclass(slots=True)
class BotInstance:
    bot_id: str
    instance_id: str
    display_name: str
    platform: str
    assigned_team_id: str | None = None
    assigned_role: str | None = None
    logic_version: str = "championship-mvp"
    config_version: str = "1"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BotRuntimeStatus:
    bot_id: str
    match_id: str | None = None
    match_context_version: int = 0
    process_state: str = "inactive"
    workflow_state: str = "not_ready"
    selected_brawler: str | None = None
    last_heartbeat_at: str | None = None
    last_error_code: str | None = None
    last_error_reason: str | None = None
    responsive: bool = False
    active_pid: int | None = None
    command_id: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PickAssignment:
    assignment_id: str
    match_id: str
    match_context_version: int
    team_id: str
    bot_id: str
    brawler: str
    state: str
    issued_at: str
    started_at: str | None = None
    confirmed_at: str | None = None
    pick_package: dict[str, Any] = field(default_factory=dict)
    loadout_state: str = "loadout_not_requested"
    loadout_result: dict[str, Any] = field(default_factory=dict)
    failure_code: str | None = None
    failure_reason: str | None = None


@dataclass(slots=True)
class CommandExecution:
    command_id: str
    idempotency_key: str
    command_type: str
    target_bot_id: str | None
    match_id: str | None
    match_context_version: int
    payload: dict[str, Any]
    state: str
    issued_at: str
    accepted_at: str | None = None
    completed_at: str | None = None
    failure_code: str | None = None
    failure_reason: str | None = None


@dataclass(slots=True)
class MatchStartBlocker:
    code: str
    severity: str
    message: str
    bot_id: str | None = None
    team_id: str | None = None
    recoverable: bool = True
    suggested_action: str | None = None


@dataclass(slots=True)
class MatchRuntimeAttachment:
    match_id: str
    bot_id: str
    instance_serial: str
    instance_label: str
    vendor: str
    model: str | None = None
    port: int | None = None
    match_confidence: float = 0.0
    attached_at: str | None = None
    attached_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ManualOverrideRecord:
    override_id: str
    actor: str
    timestamp: str
    reason: str
    target_entity: str
    effect: str


@dataclass(slots=True)
class ControlPlaneHealth:
    coordinator_alive: bool
    database_writable: bool
    observer_healthy: bool
    last_checked_at: str
    degraded_reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Team:
    team_id: str
    name: str
    color: str
    bot_ids: list[str] = field(default_factory=list)
    roles: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Tournament:
    tournament_id: str
    name: str
    status: str
    stage: str
    team_ids: list[str]
    current_match_id: str | None = None
    winner_team_id: str | None = None
    created_at: str | None = None
    finished_at: str | None = None


@dataclass(slots=True)
class TournamentStageRecord:
    stage_id: str
    tournament_id: str
    kind: str
    order_index: int
    status: str
    match_id: str | None
    winner_team_id: str | None = None


@dataclass(slots=True)
class Match:
    match_id: str
    tournament_id: str
    stage: str
    mode: str | None
    map_name: str | None
    best_of: int
    team_a_id: str
    team_b_id: str
    match_context_version: int
    status: str
    start_time: str | None = None
    end_time: str | None = None
    winner_team_id: str | None = None


@dataclass(slots=True)
class DraftPlan:
    draft_id: str
    match_id: str
    match_context_version: int
    mode: str
    map_name: str
    team_a_final: list[str]
    team_b_final: list[str]
    team_a_packages: list[dict[str, Any]]
    team_b_packages: list[dict[str, Any]]
    source_provider: str
    seed: int
    generated_at: str
    meta_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CommunicationMessage:
    message_id: str
    timestamp: str
    match_id: str
    match_context_version: int
    team_id: str
    from_bot_id: str
    type: str
    signal: str
    payload: dict[str, Any]
    urgency: str = "normal"
    ttl_ms: int = 5000


@dataclass(slots=True)
class ObserverNote:
    note_id: str
    match_id: str
    match_context_version: int
    timestamp: str
    severity: str
    signal: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NarrativeEvent:
    event_id: str
    match_id: str
    match_context_version: int
    timestamp: str
    category: str
    title: str
    summary: str
    team_focus: str | None = None
    confidence: float = 0.5


@dataclass(slots=True)
class HighlightCandidate:
    highlight_id: str
    match_id: str
    match_context_version: int
    timestamp_start: float
    timestamp_end: float
    event_type: str
    priority_score: float
    team_focus: str | None
    short_title: str
    short_summary: str


@dataclass(slots=True)
class MVPScore:
    match_id: str
    match_context_version: int
    bot_id: str
    objective_score: float
    pressure_score: float
    survival_score: float
    clutch_score: float
    stability_score: float
    total_score: float


@dataclass(slots=True)
class MatchReport:
    match_id: str
    tournament_id: str
    match_context_version: int
    stage: str
    mode: str | None
    map_name: str | None
    draft_a: list[str]
    draft_b: list[str]
    winner: str | None
    mvp_bot_id: str | None
    duration_sec: float
    key_moment: str | None
    tactical_summary: str
    observer_notes: list[dict[str, Any]]
    top_moments: list[dict[str, Any]]
    narrative_summary: str
    draft_a_packages: list[dict[str, Any]] = field(default_factory=list)
    draft_b_packages: list[dict[str, Any]] = field(default_factory=list)
    manual_overrides: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class MatchLobbyViewModel:
    match_id: str
    match_context_version: int
    mode: str | None
    map_name: str | None
    team_a_panel: dict[str, Any]
    team_b_panel: dict[str, Any]
    all_ready: bool
    blockers: list[dict[str, Any]]
    observer_ready: bool
    match_start_allowed: bool
