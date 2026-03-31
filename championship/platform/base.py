from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Iterable

from championship.enums import BlockerSeverity, MatchStatus
from championship.error_codes import FRIENDLY_LOBBY_NOT_DETECTED, LOBBY_NOT_ESTABLISHED
from championship.models import MatchStartBlocker


def _token_blob(tokens: Iterable[str]) -> str:
    return " ".join(tokens)


@dataclass(slots=True)
class FriendlyBattleSnapshot:
    adapter_name: str
    base_state: str
    workflow_state: str
    lobby_established: bool
    expected_lobby_state: bool
    friendly_lobby_detected: bool
    start_button_visible: bool
    matchmaking_entered: bool
    match_started_confirmed: bool
    queue_exit_visible: bool
    ocr_available: bool = False
    text_tokens: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlatformAdapter:
    name: str
    friendly_keywords: tuple[str, ...] = ()
    start_button_keywords: tuple[str, ...] = ("play",)
    matchmaking_keywords: tuple[str, ...] = ("exit", "cancel", "searching")
    queue_exit_keywords: tuple[str, ...] = ("exit", "cancel")
    require_explicit_friendly_text: bool = False
    start_key: str = "Q"
    ocr_interval_seconds: float = 1.0
    start_timeout_seconds: float = 12.0

    def _normalize_tokens(self, tokens: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for token in tokens:
            clean = re.sub(r"[^a-z0-9]+", " ", str(token).lower()).strip()
            if not clean:
                continue
            normalized.append(clean)
        return normalized

    def _extract_text_tokens(self, frame: Any) -> tuple[list[str], bool]:
        try:
            import numpy as np
            import utils  # type: ignore

            raw = utils.extract_text_and_positions(np.array(frame))
        except Exception:
            return [], False
        return self._normalize_tokens(raw.keys()), True

    def _contains_keyword(self, tokens: Iterable[str], keywords: Iterable[str]) -> bool:
        blob = _token_blob(tokens)
        return any(keyword.lower() in blob for keyword in keywords)

    def analyze_runtime_state(
        self,
        frame: Any,
        *,
        base_state: str,
        workflow_state: str,
        guard_active: bool,
        had_game_data: bool,
        is_host: bool,
    ) -> FriendlyBattleSnapshot:
        needs_ocr = base_state in {"lobby", "match", "play_store", "brawler_selection"} or guard_active
        if needs_ocr:
            text_tokens, ocr_available = self._extract_text_tokens(frame)
        else:
            text_tokens, ocr_available = [], False

        lobby_established = base_state == "lobby"
        friendly_lobby_detected = lobby_established and self._contains_keyword(text_tokens, self.friendly_keywords)
        start_button_visible = lobby_established and (
            self._contains_keyword(text_tokens, self.start_button_keywords) or (is_host and not text_tokens)
        )
        expected_lobby_state = lobby_established and (
            friendly_lobby_detected or not self.require_explicit_friendly_text
        )
        matchmaking_entered = (
            workflow_state == "matchmaking"
            or guard_active
            or self._contains_keyword(text_tokens, self.matchmaking_keywords)
        )
        match_started_confirmed = workflow_state == "in_match" or had_game_data
        queue_exit_visible = self._contains_keyword(text_tokens, self.queue_exit_keywords)

        notes: list[str] = []
        if lobby_established and not expected_lobby_state:
            notes.append("friendly_lobby_not_confident")
        if is_host and lobby_established and not start_button_visible:
            notes.append("start_button_not_visible")

        return FriendlyBattleSnapshot(
            adapter_name=self.name,
            base_state=base_state,
            workflow_state=workflow_state,
            lobby_established=lobby_established,
            expected_lobby_state=expected_lobby_state,
            friendly_lobby_detected=friendly_lobby_detected,
            start_button_visible=start_button_visible,
            matchmaking_entered=matchmaking_entered,
            match_started_confirmed=match_started_confirmed,
            queue_exit_visible=queue_exit_visible,
            ocr_available=ocr_available,
            text_tokens=text_tokens[:20],
            notes=notes,
        )

    def build_lobby_blockers(
        self,
        *,
        bot_id: str,
        team_id: str | None,
        snapshot: dict[str, Any] | None,
        is_host: bool,
        match_status: str,
    ) -> list[MatchStartBlocker]:
        if match_status not in {MatchStatus.READY_CHECK, MatchStatus.LOBBY_SETUP, MatchStatus.STARTING}:
            return []

        if not snapshot:
            return [
                MatchStartBlocker(
                    code=LOBBY_NOT_ESTABLISHED,
                    severity=BlockerSeverity.ERROR,
                    message=f"Bot {bot_id} has not reported any friendly battle handshake snapshot yet.",
                    bot_id=bot_id,
                    team_id=team_id,
                    suggested_action="Wait for heartbeat or relaunch the worker.",
                )
            ]

        blockers: list[MatchStartBlocker] = []
        if not snapshot.get("lobby_established"):
            blockers.append(
                MatchStartBlocker(
                    code=LOBBY_NOT_ESTABLISHED,
                    severity=BlockerSeverity.ERROR,
                    message=(
                        f"Host bot {bot_id} is not in lobby "
                        f"(seen base_state={snapshot.get('base_state')}, workflow={snapshot.get('workflow_state')})."
                        if is_host
                        else (
                            f"Bot {bot_id} is not in the expected lobby state "
                            f"(seen base_state={snapshot.get('base_state')}, workflow={snapshot.get('workflow_state')})."
                        )
                    ),
                    bot_id=bot_id,
                    team_id=team_id,
                    suggested_action="Return the client to lobby before starting the match.",
                )
            )
        elif not snapshot.get("expected_lobby_state"):
            blockers.append(
                MatchStartBlocker(
                    code=FRIENDLY_LOBBY_NOT_DETECTED,
                    severity=BlockerSeverity.WARNING,
                    message=(
                        f"Could not confidently confirm friendly battle lobby for bot {bot_id} "
                        f"(base_state={snapshot.get('base_state')}, notes={snapshot.get('notes') or []})."
                    ),
                    bot_id=bot_id,
                    team_id=team_id,
                    suggested_action="Verify the custom room manually if match start keeps failing.",
                )
            )

        if is_host and snapshot.get("lobby_established") and not snapshot.get("start_button_visible"):
            blockers.append(
                MatchStartBlocker(
                    code="HOST_START_TRIGGER_HIDDEN",
                    severity=BlockerSeverity.WARNING,
                    message=(
                        f"Host bot {bot_id} does not currently expose a visible start trigger "
                        f"(base_state={snapshot.get('base_state')}, notes={snapshot.get('notes') or []})."
                    ),
                    bot_id=bot_id,
                    team_id=team_id,
                    suggested_action="Make sure the host client is on the friendly battle start screen.",
                )
            )
        return blockers

    def perform_start_matchmaking(self, window_controller_obj, snapshot: FriendlyBattleSnapshot) -> None:
        if not snapshot.lobby_established:
            raise RuntimeError("Cannot start matchmaking outside of lobby.")
        window_controller_obj.keys_up(list("wasd"))
        window_controller_obj.press_key(self.start_key)
