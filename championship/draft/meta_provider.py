from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MODE_ALIASES: dict[str, tuple[str, ...]] = {
    "brawlball": ("brawlball", "brawl ball", "brawl_ball"),
    "gemgrab": ("gemgrab", "gem grab"),
    "heist": ("heist",),
    "bounty": ("bounty",),
    "knockout": ("knockout",),
    "wipeout": ("wipeout",),
    "brawlhockey": ("brawlhockey", "brawl hockey", "hockey"),
    "hotzone": ("hotzone", "hot zone"),
    "treasurehunt": ("treasurehunt", "treasure hunt"),
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch.lower() for ch in value if ch.isalnum())


def normalize_mode(value: str | None) -> str:
    token = normalize_text(value)
    for normalized, aliases in MODE_ALIASES.items():
        if token in {normalize_text(alias) for alias in aliases}:
            return normalized
    return token


def normalize_map_name(value: str | None) -> str:
    return normalize_text(value)


@dataclass(slots=True)
class LoadoutRecommendation:
    gadget_slot: int | None = None
    star_power_slot: int | None = None
    gear_slots: list[int] = field(default_factory=list)
    hypercharge_enabled: bool | None = None
    confidence: float = 0.0
    source: str = "unknown"
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MetaCandidate:
    brawler: str
    roles: list[str]
    score: float
    win_rate: float | None = None
    pick_rate: float | None = None
    rank: int | None = None
    source: str = "unknown"
    trophy_range: str | None = None
    source_section: str = "best_picks"
    raw_source_debug: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TopTeamComposition:
    brawlers: list[str]
    win_rate: float | None = None
    uses: int | None = None
    source: str = "top_teams"
    raw_source_debug: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MetaSnapshot:
    source: str
    mode: str
    map_name: str
    trophy_range: str | None
    best_picks: list[MetaCandidate]
    top_teams: list[TopTeamComposition]
    confidence: float
    fetched_at: str
    raw_source_debug: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PickPackage:
    brawler: str
    roles: list[str]
    pick_score: float
    mode: str
    map_name: str
    source: str
    trophy_range: str | None
    confidence: float
    win_rate: float | None = None
    pick_rate: float | None = None
    source_section: str = "best_picks"
    loadout: LoadoutRecommendation = field(default_factory=LoadoutRecommendation)
    raw_source_debug: dict[str, Any] = field(default_factory=dict)


class MetaProvider:
    provider_name = "base"

    def get_meta(self, mode: str, map_name: str, *, preferred_trophy_ranges: list[str] | None = None) -> MetaSnapshot:
        raise NotImplementedError

    def get_candidates(self, mode: str, map_name: str, *, preferred_trophy_ranges: list[str] | None = None) -> list[MetaCandidate]:
        return self.get_meta(mode, map_name, preferred_trophy_ranges=preferred_trophy_ranges).best_picks
