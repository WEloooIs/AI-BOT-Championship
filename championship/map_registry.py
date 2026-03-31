from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from championship.draft.meta_provider import normalize_map_name, normalize_mode


BASE_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BASE_DIR / "championship" / "assets"
MODE_ICONS_DIR = ASSETS_DIR / "mode_icons"
MAP_PREVIEWS_DIR = ASSETS_DIR / "map_previews"


@dataclass(frozen=True, slots=True)
class MapRegistryEntry:
    map_id: str
    display_name: str
    mode_id: str
    preview_path: Path


@dataclass(frozen=True, slots=True)
class ModeRegistryEntry:
    mode_id: str
    display_name: str
    subtitle: str
    accent: str
    icon_path: Path
    maps: tuple[MapRegistryEntry, ...]


def _map(mode_id: str, map_id: str, display_name: str) -> MapRegistryEntry:
    return MapRegistryEntry(
        map_id=map_id,
        display_name=display_name,
        mode_id=mode_id,
        preview_path=MAP_PREVIEWS_DIR / mode_id / f"{map_id}.png",
    )


MODE_REGISTRY: dict[str, ModeRegistryEntry] = {
    "brawlball": ModeRegistryEntry(
        mode_id="brawlball",
        display_name="Brawl Ball",
        subtitle="Score two goals to win",
        accent="#273447",
        icon_path=MODE_ICONS_DIR / "brawlball.png",
        maps=(
            _map("brawlball", "beach_ball", "Beach Ball"),
            _map("brawlball", "sneaky_fields", "Sneaky Fields"),
            _map("brawlball", "backyard_bowl", "Backyard Bowl"),
            _map("brawlball", "pinhole_punt", "Pinhole Punt"),
            _map("brawlball", "sidetrack", "Sidetrack"),
            _map("brawlball", "nutmeg", "Nutmeg"),
        ),
    ),
    "gemgrab": ModeRegistryEntry(
        mode_id="gemgrab",
        display_name="Gem Grab",
        subtitle="Grab 10 gems to win",
        accent="#3a2349",
        icon_path=MODE_ICONS_DIR / "gemgrab.png",
        maps=(
            _map("gemgrab", "railroad_robbery", "Railroad Robbery"),
            _map("gemgrab", "snake_pit", "Snake Pit"),
            _map("gemgrab", "fortress_fall", "Fortress Fall"),
            _map("gemgrab", "hard_rock_mine", "Hard Rock Mine"),
            _map("gemgrab", "gem_fort", "Gem Fort"),
            _map("gemgrab", "storage_sector", "Storage Sector"),
        ),
    ),
    "bounty": ModeRegistryEntry(
        mode_id="bounty",
        display_name="Bounty",
        subtitle="Defeat brawlers for stars",
        accent="#193741",
        icon_path=MODE_ICONS_DIR / "bounty.png",
        maps=(
            _map("bounty", "hideout", "Hideout"),
            _map("bounty", "layer_cake", "Layer Cake"),
            _map("bounty", "watermelons", "Watermelons"),
            _map("bounty", "dry_season", "Dry Season"),
            _map("bounty", "hit_and_run", "Hit and Run"),
            _map("bounty", "shooting_star", "Shooting Star"),
        ),
    ),
    "heist": ModeRegistryEntry(
        mode_id="heist",
        display_name="Heist",
        subtitle="Shoot open the enemy safe",
        accent="#442a52",
        icon_path=MODE_ICONS_DIR / "heist.png",
        maps=(
            _map("heist", "aridity", "Aridity"),
            _map("heist", "hot_potato", "Hot Potato"),
            _map("heist", "perpetual_motion", "Perpetual Motion"),
            _map("heist", "plain_text", "Plain Text"),
            _map("heist", "quintillion", "Quintillion"),
            _map("heist", "safe_zone", "Safe Zone"),
        ),
    ),
    "knockout": ModeRegistryEntry(
        mode_id="knockout",
        display_name="Knockout",
        subtitle="Defeat opposing brawlers",
        accent="#5b4322",
        icon_path=MODE_ICONS_DIR / "knockout.png",
        maps=(
            _map("knockout", "crab_claws", "Crab Claws"),
            _map("knockout", "belles_rock", "Belle's Rock"),
            _map("knockout", "healthy_middle_ground", "Healthy Middle Ground"),
            _map("knockout", "new_perspective", "New Perspective"),
            _map("knockout", "deep_end", "Deep End"),
            _map("knockout", "out_in_the_open", "Out in the Open"),
        ),
    ),
    "hotzone": ModeRegistryEntry(
        mode_id="hotzone",
        display_name="Hot Zone",
        subtitle="Capture all Hot Zones",
        accent="#5a2a2a",
        icon_path=MODE_ICONS_DIR / "hotzone.png",
        maps=(
            _map("hotzone", "dueling_beetles", "Dueling Beetles"),
            _map("hotzone", "open_business", "Open Business"),
            _map("hotzone", "parallel_plays", "Parallel Plays"),
            _map("hotzone", "hyacinth_house", "Hyacinth House"),
            _map("hotzone", "tax_evasion", "Tax Evasion"),
            _map("hotzone", "open_zone", "Open Zone"),
        ),
    ),
    "wipeout": ModeRegistryEntry(
        mode_id="wipeout",
        display_name="Wipeout",
        subtitle="Defeat opponents",
        accent="#173b45",
        icon_path=MODE_ICONS_DIR / "wipeout.png",
        maps=(
            _map("wipeout", "walking_on_hot_sand", "Walking on Hot Sand"),
            _map("wipeout", "palette_hangout", "Palette Hangout"),
            _map("wipeout", "too_gimmicky_2", "Too Gimmicky 2"),
            _map("wipeout", "catacombs", "Catacombs"),
            _map("wipeout", "deathmatch", "Deathmatch"),
            _map("wipeout", "wonderland", "Wonderland"),
        ),
    ),
    "brawlhockey": ModeRegistryEntry(
        mode_id="brawlhockey",
        display_name="Brawl Hockey",
        subtitle="Score three goals to win",
        accent="#2f3448",
        icon_path=MODE_ICONS_DIR / "brawlhockey.png",
        maps=(
            _map("brawlhockey", "slippery_slap", "Slippery Slap"),
            _map("brawlhockey", "super_center", "Super Center"),
            _map("brawlhockey", "below_zero", "Below Zero"),
            _map("brawlhockey", "bouncy_bowl", "Bouncy Bowl"),
            _map("brawlhockey", "cabin_fever", "Cabin Fever"),
            _map("brawlhockey", "tip_toe", "Tip Toe"),
        ),
    ),
}


def ordered_modes() -> list[ModeRegistryEntry]:
    return list(MODE_REGISTRY.values())


def get_mode_entry(mode_id: str | None) -> ModeRegistryEntry | None:
    normalized = normalize_mode(mode_id)
    return MODE_REGISTRY.get(normalized)


def maps_for_mode(mode_id: str | None) -> list[MapRegistryEntry]:
    entry = get_mode_entry(mode_id)
    return list(entry.maps) if entry else []


def get_map_entry(mode_id: str | None, map_name: str | None) -> MapRegistryEntry | None:
    mode_entry = get_mode_entry(mode_id)
    if mode_entry is None:
        return None
    normalized_target = normalize_map_name(map_name)
    for item in mode_entry.maps:
        if normalize_map_name(item.display_name) == normalized_target or item.map_id == normalized_target:
            return item
    return None


def default_map_for_mode(mode_id: str | None) -> MapRegistryEntry | None:
    maps = maps_for_mode(mode_id)
    return maps[0] if maps else None
