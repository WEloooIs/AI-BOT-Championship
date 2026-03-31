from __future__ import annotations

from dataclasses import replace

from championship.draft.meta_provider import LoadoutRecommendation, normalize_mode


DEFAULT_LOADOUT = LoadoutRecommendation(
    gadget_slot=1,
    star_power_slot=1,
    gear_slots=[1, 2],
    hypercharge_enabled=None,
    confidence=0.45,
    source="static_default_build",
    notes=["generic fallback build"],
)

ROLE_HINTS: dict[str, list[str]] = {
    "barley": ["support", "objective"],
    "stu": ["aggro", "flex"],
    "gene": ["support", "anchor"],
    "sandy": ["support", "flex"],
    "max": ["support", "aggro"],
    "tara": ["anchor", "support"],
    "rico": ["anchor", "aggro"],
    "griff": ["objective", "flex"],
    "colt": ["objective", "aggro"],
    "jessie": ["support", "objective"],
    "colette": ["objective", "flex"],
    "nita": ["support", "objective"],
    "brock": ["aggro", "flex"],
    "piper": ["anchor", "aggro"],
    "belle": ["anchor", "support"],
    "tick": ["support", "anchor"],
    "nani": ["aggro", "anchor"],
    "gray": ["flex", "objective"],
    "otis": ["aggro", "flex"],
    "bull": ["objective", "aggro"],
    "bibi": ["aggro", "flex"],
    "crow": ["aggro", "flex"],
    "edgar": ["aggro"],
    "mico": ["aggro"],
    "chuck": ["objective", "flex"],
}


BRAWLER_DEFAULTS: dict[str, LoadoutRecommendation] = {
    "barley": LoadoutRecommendation(gadget_slot=1, star_power_slot=2, gear_slots=[2, 4], confidence=0.78, source="static_curated"),
    "stu": LoadoutRecommendation(gadget_slot=1, star_power_slot=2, gear_slots=[1, 3], hypercharge_enabled=True, confidence=0.81, source="static_curated"),
    "gene": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 5], confidence=0.82, source="static_curated"),
    "sandy": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 5], hypercharge_enabled=True, confidence=0.83, source="static_curated"),
    "max": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[1, 5], hypercharge_enabled=True, confidence=0.8, source="static_curated"),
    "tara": LoadoutRecommendation(gadget_slot=2, star_power_slot=1, gear_slots=[2, 5], hypercharge_enabled=True, confidence=0.74, source="static_curated"),
    "rico": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 3], hypercharge_enabled=True, confidence=0.79, source="static_curated"),
    "griff": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 4], hypercharge_enabled=True, confidence=0.72, source="static_curated"),
    "colt": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 4], hypercharge_enabled=True, confidence=0.77, source="static_curated"),
    "jessie": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 4], hypercharge_enabled=True, confidence=0.76, source="static_curated"),
    "colette": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 4], hypercharge_enabled=True, confidence=0.79, source="static_curated"),
    "nita": LoadoutRecommendation(gadget_slot=2, star_power_slot=1, gear_slots=[2, 5], hypercharge_enabled=True, confidence=0.73, source="static_curated"),
    "brock": LoadoutRecommendation(gadget_slot=1, star_power_slot=2, gear_slots=[2, 3], hypercharge_enabled=True, confidence=0.76, source="static_curated"),
    "piper": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 3], hypercharge_enabled=True, confidence=0.82, source="static_curated"),
    "belle": LoadoutRecommendation(gadget_slot=1, star_power_slot=2, gear_slots=[2, 3], hypercharge_enabled=True, confidence=0.8, source="static_curated"),
    "tick": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 4], hypercharge_enabled=True, confidence=0.79, source="static_curated"),
    "nani": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 3], hypercharge_enabled=True, confidence=0.78, source="static_curated"),
    "gray": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 5], hypercharge_enabled=True, confidence=0.77, source="static_curated"),
    "otis": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 5], hypercharge_enabled=True, confidence=0.75, source="static_curated"),
    "bull": LoadoutRecommendation(gadget_slot=1, star_power_slot=1, gear_slots=[1, 4], hypercharge_enabled=True, confidence=0.68, source="static_curated"),
    "bibi": LoadoutRecommendation(gadget_slot=1, star_power_slot=2, gear_slots=[1, 5], hypercharge_enabled=True, confidence=0.7, source="static_curated"),
    "crow": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[1, 2], hypercharge_enabled=True, confidence=0.74, source="static_curated"),
    "edgar": LoadoutRecommendation(gadget_slot=2, star_power_slot=1, gear_slots=[1, 4], hypercharge_enabled=True, confidence=0.69, source="static_curated"),
    "mico": LoadoutRecommendation(gadget_slot=2, star_power_slot=1, gear_slots=[1, 5], hypercharge_enabled=True, confidence=0.66, source="static_curated"),
    "chuck": LoadoutRecommendation(gadget_slot=2, star_power_slot=2, gear_slots=[2, 4], hypercharge_enabled=True, confidence=0.7, source="static_curated"),
}


MODE_GEAR_OVERRIDES: dict[str, list[int]] = {
    "heist": [2, 4],
    "brawlball": [1, 5],
    "gemgrab": [2, 5],
    "knockout": [2, 3],
    "wipeout": [2, 3],
    "brawlhockey": [1, 5],
}


class LoadoutRecommender:
    def recommend(self, *, mode: str, map_name: str, brawler: str, roles: list[str]) -> LoadoutRecommendation:
        del map_name, roles
        normalized_brawler = (brawler or "").lower().strip()
        base = replace(BRAWLER_DEFAULTS.get(normalized_brawler, DEFAULT_LOADOUT))
        mode_key = normalize_mode(mode)
        override_gears = MODE_GEAR_OVERRIDES.get(mode_key)
        if override_gears:
            base.gear_slots = list(override_gears)
            if normalized_brawler in BRAWLER_DEFAULTS:
                base.notes.append(f"mode override for {mode_key}")
        return base


def infer_roles(brawler: str) -> list[str]:
    return list(ROLE_HINTS.get((brawler or "").lower().strip(), ["flex"]))
