from __future__ import annotations

from datetime import UTC, datetime

from championship.draft.meta_provider import MetaCandidate, MetaProvider, MetaSnapshot, TopTeamComposition, normalize_mode


STATIC_MODE_POOLS: dict[str, list[MetaCandidate]] = {
    "brawlball": [
        MetaCandidate("barley", ["support", "objective"], 0.88),
        MetaCandidate("stu", ["aggro", "flex"], 0.91),
        MetaCandidate("gene", ["support", "anchor"], 0.85),
        MetaCandidate("sandy", ["support", "flex"], 0.9),
        MetaCandidate("max", ["support", "aggro"], 0.89),
        MetaCandidate("tara", ["anchor", "support"], 0.82),
    ],
    "gemgrab": [
        MetaCandidate("gene", ["support", "anchor"], 0.92),
        MetaCandidate("sandy", ["support", "objective"], 0.9),
        MetaCandidate("max", ["support", "flex"], 0.87),
        MetaCandidate("rico", ["anchor", "aggro"], 0.84),
        MetaCandidate("barley", ["support"], 0.82),
        MetaCandidate("griff", ["objective", "flex"], 0.8),
    ],
    "heist": [
        MetaCandidate("colt", ["objective", "aggro"], 0.9),
        MetaCandidate("jessie", ["support", "objective"], 0.88),
        MetaCandidate("colette", ["objective", "flex"], 0.91),
        MetaCandidate("nita", ["support", "objective"], 0.84),
        MetaCandidate("brock", ["aggro", "flex"], 0.83),
        MetaCandidate("barley", ["support"], 0.79),
    ],
    "bounty": [
        MetaCandidate("piper", ["anchor", "aggro"], 0.9),
        MetaCandidate("belle", ["anchor", "support"], 0.88),
        MetaCandidate("tick", ["support", "anchor"], 0.86),
        MetaCandidate("gene", ["support"], 0.82),
        MetaCandidate("nani", ["aggro"], 0.84),
        MetaCandidate("max", ["flex"], 0.8),
    ],
    "knockout": [
        MetaCandidate("gene", ["support", "anchor"], 0.88),
        MetaCandidate("belle", ["anchor"], 0.87),
        MetaCandidate("brock", ["aggro", "flex"], 0.85),
        MetaCandidate("gray", ["flex", "objective"], 0.84),
        MetaCandidate("sandy", ["support"], 0.86),
        MetaCandidate("otis", ["aggro"], 0.81),
    ],
    "hotzone": [
        MetaCandidate("lou", ["objective", "anchor"], 0.91),
        MetaCandidate("sandy", ["support", "objective"], 0.89),
        MetaCandidate("amber", ["aggro", "objective"], 0.87),
        MetaCandidate("max", ["support", "flex"], 0.85),
        MetaCandidate("griff", ["objective", "flex"], 0.83),
        MetaCandidate("emz", ["anchor", "support"], 0.82),
    ],
    "wipeout": [
        MetaCandidate("belle", ["anchor"], 0.9),
        MetaCandidate("piper", ["aggro"], 0.87),
        MetaCandidate("max", ["support", "flex"], 0.84),
        MetaCandidate("sandy", ["support"], 0.83),
        MetaCandidate("brock", ["aggro"], 0.82),
        MetaCandidate("tick", ["anchor"], 0.79),
    ],
    "brawlhockey": [
        MetaCandidate("max", ["support", "aggro"], 0.88),
        MetaCandidate("stu", ["aggro"], 0.9),
        MetaCandidate("sandy", ["support"], 0.85),
        MetaCandidate("gene", ["support"], 0.83),
        MetaCandidate("tara", ["anchor"], 0.82),
        MetaCandidate("barley", ["support"], 0.78),
    ],
}


class StaticMetaProvider(MetaProvider):
    provider_name = "fallback_local"

    def get_meta(self, mode: str, map_name: str, *, preferred_trophy_ranges: list[str] | None = None) -> MetaSnapshot:
        del preferred_trophy_ranges
        normalized = normalize_mode(mode)
        picks = list(STATIC_MODE_POOLS.get(normalized, STATIC_MODE_POOLS["brawlball"]))
        for index, candidate in enumerate(picks, start=1):
            candidate.rank = index
            candidate.source = self.provider_name
            candidate.trophy_range = "fallback_local"
            candidate.source_section = "fallback_pool"
        top_teams = [
            TopTeamComposition([picks[0].brawler, picks[1].brawler, picks[2].brawler], win_rate=0.56, uses=120, source="fallback_top_team"),
            TopTeamComposition([picks[1].brawler, picks[3].brawler, picks[4].brawler], win_rate=0.54, uses=90, source="fallback_top_team"),
        ]
        return MetaSnapshot(
            source=self.provider_name,
            mode=normalized,
            map_name=map_name,
            trophy_range="fallback_local",
            best_picks=picks,
            top_teams=top_teams,
            confidence=0.35,
            fetched_at=datetime.now(UTC).isoformat(),
            raw_source_debug={"reason": "static mode pool fallback"},
        )
