from __future__ import annotations

import hashlib
import json
import re
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag

from championship.draft.loadout_recommender import infer_roles
from championship.draft.meta_provider import (
    MetaCandidate,
    MetaProvider,
    MetaSnapshot,
    TopTeamComposition,
    normalize_map_name,
    normalize_mode,
    normalize_text,
)


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "championship_data"
CACHE_DIR = DATA_DIR / "meta_cache" / "brawlify"
LOG_PATH = DATA_DIR / "meta_provider.log"
CONFIG_PATH = BASE_DIR / "cfg" / "meta_provider.toml"
EVENTS_URL = "https://brawlify.com/events"


class BrawlifyFetchError(RuntimeError):
    pass


class BrawlifyEventsProvider(MetaProvider):
    provider_name = "brawlify_events"

    def __init__(self, fallback_provider: MetaProvider | None = None) -> None:
        self.fallback_provider = fallback_provider
        self.config = self._load_config()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
        )

    def _load_config(self) -> dict[str, Any]:
        defaults = {
            "timeout_seconds": 20,
            "cache_ttl_seconds": 21600,
            "preferred_trophy_ranges": ["1000+", "500-999", "all"],
        }
        if not CONFIG_PATH.exists():
            return defaults
        with CONFIG_PATH.open("rb") as handle:
            parsed = tomllib.load(handle)
        section = parsed.get("brawlify", {})
        result = dict(defaults)
        result.update(section)
        return result

    def _log(self, message: str, **details: Any) -> None:
        payload = {"timestamp": datetime.now(UTC).isoformat(), "message": message, "details": details}
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return CACHE_DIR / f"{digest}.json"

    def _read_cache(self, url: str) -> str | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        fetched_at = float(payload.get("fetched_at", 0.0))
        ttl = int(self.config.get("cache_ttl_seconds", 21600))
        if time.time() - fetched_at > ttl:
            return None
        return str(payload.get("html") or "")

    def _write_cache(self, url: str, html: str) -> None:
        self._cache_path(url).write_text(
            json.dumps({"fetched_at": time.time(), "html": html}, ensure_ascii=False),
            encoding="utf-8",
        )

    def _fetch_html(self, url: str) -> str:
        cached = self._read_cache(url)
        if cached:
            return cached
        timeout = float(self.config.get("timeout_seconds", 20))
        last_error = "unknown"
        strategies: list[tuple[str, Any]] = [("requests", self._fetch_with_requests)]
        try:
            from curl_cffi import requests as curl_requests  # type: ignore
        except Exception:
            curl_requests = None
        if curl_requests is not None:
            strategies.append(("curl_cffi", lambda target_url: self._fetch_with_curl(target_url, curl_requests, timeout)))
        for strategy_name, strategy in strategies:
            try:
                html = strategy(url)
                if self._is_block_page(html):
                    raise BrawlifyFetchError("security check / request blocked page returned")
                self._write_cache(url, html)
                self._log("brawlify_fetch_ok", url=url, strategy=strategy_name)
                return html
            except Exception as exc:  # pragma: no cover - depends on remote availability
                last_error = f"{strategy_name}: {exc}"
                self._log("brawlify_fetch_failed", url=url, strategy=strategy_name, error=str(exc))
        raise BrawlifyFetchError(last_error)

    def _fetch_with_requests(self, url: str) -> str:
        response = self.session.get(url, timeout=float(self.config.get("timeout_seconds", 20)))
        if response.status_code >= 400:
            raise BrawlifyFetchError(f"http {response.status_code}")
        return response.text

    def _fetch_with_curl(self, url: str, curl_requests, timeout: float) -> str:
        response = curl_requests.get(url, impersonate="chrome124", timeout=timeout)
        if response.status_code >= 400:
            raise BrawlifyFetchError(f"http {response.status_code}")
        return response.text

    @staticmethod
    def _is_block_page(html: str) -> bool:
        lowered = html.lower()
        return "request blocked" in lowered or "security check" in lowered

    def _resolve_event(self, mode: str, map_name: str) -> tuple[str, dict[str, Any]]:
        html = self._fetch_html(EVENTS_URL)
        soup = BeautifulSoup(html, "html.parser")
        target_mode = normalize_mode(mode)
        target_map = normalize_map_name(map_name)
        best_match: tuple[float, str, dict[str, Any]] | None = None

        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if "/maps/" not in href:
                continue
            text = " ".join(anchor.stripped_strings)
            if not text:
                continue
            normalized_text = normalize_text(text)
            score = 0.0
            if target_map and target_map in normalized_text:
                score += 5.0
            if target_mode and target_mode in normalized_text:
                score += 4.0
            if text.upper().startswith("LIVE"):
                score += 1.0
            if score <= 0:
                continue
            debug = {"anchor_text": text, "href": href}
            if not best_match or score > best_match[0]:
                best_match = (score, href, debug)

        if not best_match:
            raise BrawlifyFetchError(f"Could not resolve event for mode={mode} map={map_name}")
        href = best_match[1]
        if href.startswith("/"):
            href = f"https://brawlify.com{href}"
        self._log("brawlify_event_matched", mode=mode, map_name=map_name, href=href, debug=best_match[2], score=best_match[0])
        return href, best_match[2]

    def _extract_brawler_name(self, anchor: Tag) -> str | None:
        text = " ".join(anchor.stripped_strings)
        if text:
            cleaned = re.sub(r"\s+\d+(?:\.\d+)?%\s+\d+(?:\.\d+)?%.*$", "", text).strip()
            cleaned = re.sub(r"\s+\d+(?:\.\d+)?%.*$", "", cleaned).strip()
            if cleaned:
                return cleaned.lower()
        for tag in anchor.find_all(["img", "svg"]):
            for attr in ("alt", "title", "aria-label"):
                value = tag.get(attr)
                if value:
                    return str(value).split()[0].lower()
        href = anchor.get("href", "")
        match = re.search(r"/brawlers/([^/?#]+)", href)
        if match:
            return match.group(1).replace("-", " ").lower()
        return None

    def _extract_rates(self, anchor: Tag) -> tuple[float | None, float | None]:
        text = " ".join(anchor.stripped_strings)
        percents = re.findall(r"(\d+(?:\.\d+)?)%", text)
        if not percents:
            return None, None
        win_rate = float(percents[0])
        pick_rate = float(percents[1]) if len(percents) > 1 else None
        return win_rate, pick_rate

    def _section_links(self, soup: BeautifulSoup, heading_text: str) -> list[Tag]:
        target = normalize_text(heading_text)
        headings = [tag for tag in soup.find_all(["h2", "h3", "h4"]) if target in normalize_text(tag.get_text(" ", strip=True))]
        if not headings:
            return []
        start = headings[0]
        result: list[Tag] = []
        for element in start.next_elements:
            if element is start:
                continue
            if isinstance(element, Tag) and element.name in {"h2", "h3", "h4"} and element is not start:
                break
            if isinstance(element, Tag) and element.name == "a" and element.get("href"):
                result.append(element)
        return result

    def _parse_candidate_section(self, soup: BeautifulSoup, heading_text: str, source_section: str, trophy_range: str | None) -> list[MetaCandidate]:
        candidates: list[MetaCandidate] = []
        seen: set[str] = set()
        for index, anchor in enumerate(self._section_links(soup, heading_text), start=1):
            brawler = self._extract_brawler_name(anchor)
            if not brawler or brawler in seen:
                continue
            win_rate, pick_rate = self._extract_rates(anchor)
            score = (win_rate or 0.0) / 100.0
            if source_section == "most_used":
                score = max(score, (pick_rate or 0.0) / 100.0)
            seen.add(brawler)
            candidates.append(
                MetaCandidate(
                    brawler=brawler,
                    roles=infer_roles(brawler),
                    score=score,
                    win_rate=win_rate,
                    pick_rate=pick_rate,
                    rank=index,
                    source=self.provider_name,
                    trophy_range=trophy_range,
                    source_section=source_section,
                    raw_source_debug={"href": anchor.get("href"), "text": " ".join(anchor.stripped_strings)},
                )
            )
        return candidates

    def _parse_top_teams(self, soup: BeautifulSoup) -> list[TopTeamComposition]:
        anchors = self._section_links(soup, "Top Teams")
        team_brawlers: list[str] = []
        teams: list[TopTeamComposition] = []
        for anchor in anchors:
            brawler = self._extract_brawler_name(anchor)
            if not brawler:
                continue
            team_brawlers.append(brawler)
            if len(team_brawlers) == 3:
                teams.append(
                    TopTeamComposition(
                        brawlers=list(team_brawlers),
                        source="top_teams",
                        raw_source_debug={"hrefs": [item.get("href") for item in anchors[:3]]},
                    )
                )
                team_brawlers = []
            if len(teams) >= 10:
                break
        return teams

    def _combine_sections(
        self,
        *sections: list[MetaCandidate],
    ) -> list[MetaCandidate]:
        merged: dict[str, MetaCandidate] = {}
        section_priority = {"best_picks": 1.0, "winners": 0.94, "most_used": 0.88, "fallback_pool": 0.7}
        for section in sections:
            for candidate in section:
                existing = merged.get(candidate.brawler)
                candidate_score = candidate.score * section_priority.get(candidate.source_section, 0.8)
                if existing is None or candidate_score > existing.score:
                    merged[candidate.brawler] = MetaCandidate(
                        brawler=candidate.brawler,
                        roles=list(candidate.roles),
                        score=candidate_score,
                        win_rate=candidate.win_rate,
                        pick_rate=candidate.pick_rate,
                        rank=candidate.rank,
                        source=candidate.source,
                        trophy_range=candidate.trophy_range,
                        source_section=candidate.source_section,
                        raw_source_debug=dict(candidate.raw_source_debug),
                    )
        return sorted(merged.values(), key=lambda item: item.score, reverse=True)

    def _parse_map_page(
        self,
        html: str,
        *,
        mode: str,
        map_name: str,
        trophy_range: str | None,
        event_debug: dict[str, Any],
    ) -> MetaSnapshot:
        soup = BeautifulSoup(html, "html.parser")
        normalized_mode = normalize_mode(mode)
        normalized_map = normalize_map_name(map_name)
        best_picks = self._parse_candidate_section(soup, "Best Picks", "best_picks", trophy_range)
        winners = self._parse_candidate_section(soup, "Winners", "winners", trophy_range)
        most_used = self._parse_candidate_section(soup, "Most Used", "most_used", trophy_range)
        combined = self._combine_sections(best_picks, winners, most_used)
        top_teams = self._parse_top_teams(soup)
        confidence = 0.9 if len(best_picks) >= 6 else 0.72 if len(combined) >= 6 else 0.45
        return MetaSnapshot(
            source=self.provider_name,
            mode=normalized_mode,
            map_name=map_name,
            trophy_range=trophy_range,
            best_picks=combined,
            top_teams=top_teams,
            confidence=confidence,
            fetched_at=datetime.now(UTC).isoformat(),
            raw_source_debug={
                "event_debug": event_debug,
                "best_pick_count": len(best_picks),
                "winner_count": len(winners),
                "most_used_count": len(most_used),
                "normalized_mode": normalized_mode,
                "normalized_map": normalized_map,
            },
        )

    def get_meta(self, mode: str, map_name: str, *, preferred_trophy_ranges: list[str] | None = None) -> MetaSnapshot:
        preferred_ranges = preferred_trophy_ranges or list(self.config.get("preferred_trophy_ranges", ["1000+", "500-999", "all"]))
        errors: list[str] = []
        for trophy_range in preferred_ranges:
            try:
                event_url, event_debug = self._resolve_event(mode, map_name)
                url = event_url if trophy_range in {"all", "", None} else f"{event_url}?range={requests.utils.quote(str(trophy_range))}"
                html = self._fetch_html(url)
                snapshot = self._parse_map_page(
                    html,
                    mode=mode,
                    map_name=map_name,
                    trophy_range=None if trophy_range in {"all", "", None} else str(trophy_range),
                    event_debug=event_debug,
                )
                if len(snapshot.best_picks) >= 6:
                    self._log(
                        "brawlify_meta_ok",
                        mode=mode,
                        map_name=map_name,
                        trophy_range=trophy_range,
                        matched_event=event_debug,
                        best_pick_count=len(snapshot.best_picks),
                    )
                    return snapshot
                errors.append(f"{trophy_range}: insufficient candidates ({len(snapshot.best_picks)})")
            except Exception as exc:
                errors.append(f"{trophy_range}: {exc}")
        self._log("brawlify_fallback_local", mode=mode, map_name=map_name, errors=errors)
        if self.fallback_provider is None:
            raise BrawlifyFetchError("; ".join(errors) or "Brawlify provider failed")
        snapshot = self.fallback_provider.get_meta(mode, map_name, preferred_trophy_ranges=preferred_ranges)
        snapshot.raw_source_debug = {**snapshot.raw_source_debug, "fallback_reason": errors, "primary_source": self.provider_name}
        return snapshot
