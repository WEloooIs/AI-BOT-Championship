from __future__ import annotations

import random
from dataclasses import dataclass

from championship.draft.anti_repeat import comp_signature, same_full_comp
from championship.draft.loadout_recommender import LoadoutRecommender
from championship.draft.meta_provider import MetaCandidate, MetaProvider, MetaSnapshot, PickPackage


@dataclass(slots=True)
class DraftBuildResult:
    team_a_packages: list[PickPackage]
    team_b_packages: list[PickPackage]
    meta_snapshot: MetaSnapshot


class DraftBuilder:
    def __init__(self, provider: MetaProvider, loadout_recommender: LoadoutRecommender | None = None) -> None:
        self.provider = provider
        self.loadout_recommender = loadout_recommender or LoadoutRecommender()

    def _package_from_candidate(self, candidate: MetaCandidate, *, mode: str, map_name: str) -> PickPackage:
        loadout = self.loadout_recommender.recommend(
            mode=mode,
            map_name=map_name,
            brawler=candidate.brawler,
            roles=candidate.roles,
        )
        confidence = min(0.98, max(candidate.score, loadout.confidence))
        return PickPackage(
            brawler=candidate.brawler,
            roles=list(candidate.roles),
            pick_score=candidate.score,
            mode=mode,
            map_name=map_name,
            source=candidate.source,
            trophy_range=candidate.trophy_range,
            confidence=confidence,
            win_rate=candidate.win_rate,
            pick_rate=candidate.pick_rate,
            source_section=candidate.source_section,
            loadout=loadout,
            raw_source_debug=dict(candidate.raw_source_debug),
        )

    def _build_from_top_teams(
        self,
        snapshot: MetaSnapshot,
        *,
        last_comp_signatures: set[str],
    ) -> tuple[list[str], list[str]] | None:
        if len(snapshot.top_teams) < 2:
            return None
        seen: set[str] = set()
        teams: list[list[str]] = []
        for comp in snapshot.top_teams:
            if len(comp.brawlers) != 3:
                continue
            if len(set(comp.brawlers)) != 3:
                continue
            signature = comp_signature(comp.brawlers)
            if signature in seen:
                continue
            seen.add(signature)
            teams.append(list(comp.brawlers))
            if len(teams) >= 2:
                break
        if len(teams) < 2:
            return None
        team_a, team_b = teams[0], teams[1]
        if same_full_comp(team_a, team_b):
            return None
        if comp_signature(team_a) in last_comp_signatures and len(teams) >= 2:
            team_a = teams[1]
        if comp_signature(team_b) in last_comp_signatures and len(teams) >= 2:
            team_b = teams[0]
        return team_a, team_b

    def _build_from_candidates(
        self,
        candidates: list[MetaCandidate],
        *,
        seed: int,
        last_comp_signatures: set[str],
    ) -> tuple[list[str], list[str]]:
        rng = random.Random(seed)
        if len(candidates) < 6:
            raise ValueError("Meta provider returned too few candidates for a 3v3 draft.")
        shuffled = candidates[:]
        rng.shuffle(shuffled)
        team_a: list[str] = []
        team_b: list[str] = []

        for candidate in shuffled:
            if candidate.brawler in team_a or candidate.brawler in team_b:
                continue
            if len(team_a) < 3:
                team_a.append(candidate.brawler)
                continue
            if len(team_b) < 3:
                team_b.append(candidate.brawler)
            if len(team_a) == 3 and len(team_b) == 3:
                break

        if len(team_a) < 3 or len(team_b) < 3:
            raise ValueError("Unable to build a full 3v3 draft from the current meta pool.")
        if same_full_comp(team_a, team_b):
            team_b = list(reversed(team_b))
        if comp_signature(team_a) in last_comp_signatures:
            team_a = list(reversed(team_a))
        if comp_signature(team_b) in last_comp_signatures:
            team_b = list(reversed(team_b))
        return team_a, team_b

    def build(
        self,
        *,
        mode: str,
        map_name: str,
        seed: int,
        last_comp_signatures: set[str],
        preferred_trophy_ranges: list[str] | None = None,
    ) -> DraftBuildResult:
        snapshot = self.provider.get_meta(mode, map_name, preferred_trophy_ranges=preferred_trophy_ranges)
        team_pair = self._build_from_top_teams(snapshot, last_comp_signatures=last_comp_signatures)
        if team_pair is None:
            team_pair = self._build_from_candidates(snapshot.best_picks, seed=seed, last_comp_signatures=last_comp_signatures)
        team_a_brawlers, team_b_brawlers = team_pair
        candidate_lookup = {candidate.brawler: candidate for candidate in snapshot.best_picks}
        team_a_packages = [
            self._package_from_candidate(candidate_lookup[brawler], mode=mode, map_name=map_name)
            for brawler in team_a_brawlers
            if brawler in candidate_lookup
        ]
        team_b_packages = [
            self._package_from_candidate(candidate_lookup[brawler], mode=mode, map_name=map_name)
            for brawler in team_b_brawlers
            if brawler in candidate_lookup
        ]
        if len(team_a_packages) != 3 or len(team_b_packages) != 3:
            raise ValueError("Draft packages could not be materialized for all selected brawlers.")
        return DraftBuildResult(team_a_packages=team_a_packages, team_b_packages=team_b_packages, meta_snapshot=snapshot)
