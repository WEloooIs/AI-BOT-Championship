from __future__ import annotations

import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from championship.enums import LoadoutLifecycleState
from championship.error_codes import (
    GADGET_SET_FAILED,
    GEAR_SET_FAILED,
    HYPERCHARGE_SETUP_FAILED,
    LOADOUT_SCREEN_NOT_OPENED,
    STAR_POWER_SET_FAILED,
)


BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "cfg" / "loadout_config.toml"


@dataclass(slots=True)
class LoadoutApplyResponse:
    state: str
    result: dict[str, Any]
    error_code: str | None = None
    error_reason: str | None = None


def _load_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "flow": {
            "enabled": False,
            "allow_best_effort_without_ui": True,
            "verify_screen_with_ocr": True,
            "verification_mode": "screen_only",
            "open_delay_seconds": 0.8,
            "after_tab_delay_seconds": 0.25,
            "after_slot_delay_seconds": 0.25,
            "close_delay_seconds": 0.2,
        },
        "verification": {
            "screen_keywords": [
                "gadget",
                "gear",
                "gears",
                "star power",
                "starpower",
                "hypercharge",
            ]
        },
        "points": {
            "open_loadout": [0.52, 0.82],
            "close_loadout": [0.94, 0.09],
            "gadget_tab": [0.20, 0.30],
            "star_power_tab": [0.50, 0.30],
            "gear_tab": [0.80, 0.30],
            "gadget_slot_1": [0.35, 0.60],
            "gadget_slot_2": [0.65, 0.60],
            "star_power_slot_1": [0.35, 0.60],
            "star_power_slot_2": [0.65, 0.60],
            "gear_slot_1": [0.22, 0.57],
            "gear_slot_2": [0.50, 0.57],
            "gear_slot_3": [0.78, 0.57],
            "gear_slot_4": [0.35, 0.78],
            "gear_slot_5": [0.65, 0.78],
            "hypercharge_toggle": [0.84, 0.22],
        },
    }
    if not CONFIG_PATH.exists():
        return defaults
    with CONFIG_PATH.open("rb") as handle:
        parsed = tomllib.load(handle)
    merged = dict(defaults)
    for section in ("flow", "verification", "points"):
        merged[section] = dict(defaults.get(section, {}))
        merged[section].update(parsed.get(section, {}))
    return merged


class LoadoutAutomation:
    def __init__(self, window_controller_obj) -> None:
        self.window_controller = window_controller_obj
        self.config = _load_config()

    def _flow(self, key: str, default: Any = None) -> Any:
        return self.config.get("flow", {}).get(key, default)

    def _point(self, key: str) -> tuple[float, float] | None:
        value = self.config.get("points", {}).get(key)
        if not value or len(value) != 2:
            return None
        return float(value[0]), float(value[1])

    def _click_ratio(self, ratio_point: tuple[float, float], frame_size: tuple[int, int]) -> None:
        width, height = frame_size
        x = int(width * ratio_point[0])
        y = int(height * ratio_point[1])
        self.window_controller.click(x, y, already_include_ratio=True)

    def _frame_size(self) -> tuple[int, int]:
        frame = self.window_controller.screenshot()
        width, height = frame.size
        return width, height

    def _extract_tokens(self) -> list[str]:
        try:
            import utils  # type: ignore

            raw = utils.extract_text_and_positions(np.array(self.window_controller.screenshot()))
        except Exception:
            return []
        normalized: list[str] = []
        for key in raw.keys():
            token = "".join(ch.lower() for ch in str(key) if ch.isalnum() or ch.isspace()).strip()
            if token:
                normalized.append(token)
        return normalized

    def _screen_opened(self) -> bool:
        if not self._flow("verify_screen_with_ocr", True):
            return False
        tokens = " ".join(self._extract_tokens())
        keywords = [str(item).lower() for item in self.config.get("verification", {}).get("screen_keywords", [])]
        return any(keyword in tokens for keyword in keywords)

    def _click_named(self, point_name: str, *, frame_size: tuple[int, int], errors: list[dict[str, Any]], error_code: str | None = None) -> bool:
        point = self._point(point_name)
        if point is None:
            if error_code:
                errors.append({"error_code": error_code, "reason": f"Missing point config: {point_name}"})
            return False
        self._click_ratio(point, frame_size)
        return True

    def _apply_single_slot(
        self,
        *,
        tab_name: str,
        tab_point: str,
        slot_index: int | None,
        slot_prefix: str,
        frame_size: tuple[int, int],
        after_tab_delay: float,
        after_slot_delay: float,
        errors: list[dict[str, Any]],
        error_code: str,
    ) -> bool:
        if slot_index is None:
            return True
        if not self._click_named(tab_point, frame_size=frame_size, errors=errors, error_code=error_code):
            errors.append({"error_code": error_code, "reason": f"Could not open {tab_name} tab"})
            return False
        time.sleep(after_tab_delay)
        if not self._click_named(f"{slot_prefix}_{slot_index}", frame_size=frame_size, errors=errors, error_code=error_code):
            errors.append({"error_code": error_code, "reason": f"Could not click {tab_name} slot {slot_index}"})
            return False
        time.sleep(after_slot_delay)
        return True

    def apply_pick_package(self, pick_package: dict[str, Any]) -> LoadoutApplyResponse:
        requested_loadout = (pick_package or {}).get("loadout") or {}
        if not requested_loadout:
            return LoadoutApplyResponse(
                state=LoadoutLifecycleState.NOT_REQUESTED,
                result={"requested": {}, "applied": {}, "notes": ["no loadout requested"]},
            )

        if not self._flow("enabled", False):
            return LoadoutApplyResponse(
                state=LoadoutLifecycleState.APPLIED_BEST_EFFORT,
                result={
                    "requested": requested_loadout,
                    "applied": {},
                    "notes": ["loadout automation disabled in cfg/loadout_config.toml"],
                    "degraded_reason": "loadout automation disabled",
                },
            )

        errors: list[dict[str, Any]] = []
        notes: list[str] = []
        applied: dict[str, Any] = {}
        frame_size = self._frame_size()

        if not self._click_named("open_loadout", frame_size=frame_size, errors=errors, error_code=LOADOUT_SCREEN_NOT_OPENED):
            if self._flow("allow_best_effort_without_ui", True):
                return LoadoutApplyResponse(
                    state=LoadoutLifecycleState.APPLIED_BEST_EFFORT,
                    result={
                        "requested": requested_loadout,
                        "applied": applied,
                        "errors": errors,
                        "notes": notes,
                        "degraded_reason": "loadout screen point is not configured",
                    },
                )
            return LoadoutApplyResponse(
                state=LoadoutLifecycleState.FAILED,
                result={"requested": requested_loadout, "applied": applied, "errors": errors, "notes": notes},
                error_code=LOADOUT_SCREEN_NOT_OPENED,
                error_reason="Loadout screen point is not configured.",
            )

        time.sleep(float(self._flow("open_delay_seconds", 0.8)))
        screen_opened = self._screen_opened()
        if not screen_opened and not self._flow("allow_best_effort_without_ui", True):
            return LoadoutApplyResponse(
                state=LoadoutLifecycleState.FAILED,
                result={
                    "requested": requested_loadout,
                    "applied": applied,
                    "errors": [{"error_code": LOADOUT_SCREEN_NOT_OPENED, "reason": "OCR could not confirm loadout screen"}],
                    "notes": notes,
                    "screen_opened": False,
                },
                error_code=LOADOUT_SCREEN_NOT_OPENED,
                error_reason="OCR could not confirm that the loadout screen opened.",
            )

        after_tab_delay = float(self._flow("after_tab_delay_seconds", 0.25))
        after_slot_delay = float(self._flow("after_slot_delay_seconds", 0.25))

        if not self._apply_single_slot(
            tab_name="gadget",
            tab_point="gadget_tab",
            slot_index=requested_loadout.get("gadget_slot"),
            slot_prefix="gadget_slot",
            frame_size=frame_size,
            after_tab_delay=after_tab_delay,
            after_slot_delay=after_slot_delay,
            errors=errors,
            error_code=GADGET_SET_FAILED,
        ):
            return LoadoutApplyResponse(
                state=LoadoutLifecycleState.FAILED,
                result={"requested": requested_loadout, "applied": applied, "errors": errors, "notes": notes, "screen_opened": screen_opened},
                error_code=GADGET_SET_FAILED,
                error_reason="Could not apply gadget slot.",
            )
        if requested_loadout.get("gadget_slot") is not None:
            applied["gadget_slot"] = requested_loadout.get("gadget_slot")

        if not self._apply_single_slot(
            tab_name="star power",
            tab_point="star_power_tab",
            slot_index=requested_loadout.get("star_power_slot"),
            slot_prefix="star_power_slot",
            frame_size=frame_size,
            after_tab_delay=after_tab_delay,
            after_slot_delay=after_slot_delay,
            errors=errors,
            error_code=STAR_POWER_SET_FAILED,
        ):
            return LoadoutApplyResponse(
                state=LoadoutLifecycleState.FAILED,
                result={"requested": requested_loadout, "applied": applied, "errors": errors, "notes": notes, "screen_opened": screen_opened},
                error_code=STAR_POWER_SET_FAILED,
                error_reason="Could not apply star power slot.",
            )
        if requested_loadout.get("star_power_slot") is not None:
            applied["star_power_slot"] = requested_loadout.get("star_power_slot")

        requested_gears = [int(slot) for slot in requested_loadout.get("gear_slots") or []]
        if requested_gears:
            if not self._click_named("gear_tab", frame_size=frame_size, errors=errors, error_code=GEAR_SET_FAILED):
                return LoadoutApplyResponse(
                    state=LoadoutLifecycleState.FAILED,
                    result={"requested": requested_loadout, "applied": applied, "errors": errors, "notes": notes, "screen_opened": screen_opened},
                    error_code=GEAR_SET_FAILED,
                    error_reason="Could not open gear tab.",
                )
            time.sleep(after_tab_delay)
            for gear_slot in requested_gears:
                if not self._click_named(f"gear_slot_{gear_slot}", frame_size=frame_size, errors=errors, error_code=GEAR_SET_FAILED):
                    return LoadoutApplyResponse(
                        state=LoadoutLifecycleState.FAILED,
                        result={"requested": requested_loadout, "applied": applied, "errors": errors, "notes": notes, "screen_opened": screen_opened},
                        error_code=GEAR_SET_FAILED,
                        error_reason=f"Could not click gear slot {gear_slot}.",
                    )
                time.sleep(after_slot_delay)
            applied["gear_slots"] = requested_gears

        if requested_loadout.get("hypercharge_enabled") is True:
            if not self._click_named("hypercharge_toggle", frame_size=frame_size, errors=errors, error_code=HYPERCHARGE_SETUP_FAILED):
                return LoadoutApplyResponse(
                    state=LoadoutLifecycleState.FAILED,
                    result={"requested": requested_loadout, "applied": applied, "errors": errors, "notes": notes, "screen_opened": screen_opened},
                    error_code=HYPERCHARGE_SETUP_FAILED,
                    error_reason="Could not toggle hypercharge.",
                )
            time.sleep(after_slot_delay)
            applied["hypercharge_enabled"] = True
        elif requested_loadout.get("hypercharge_enabled") is False:
            notes.append("hypercharge disable is not explicitly automated; current preset may remain active")

        self._click_named("close_loadout", frame_size=frame_size, errors=errors)
        time.sleep(float(self._flow("close_delay_seconds", 0.2)))

        state = LoadoutLifecycleState.VERIFIED_PARTIAL if screen_opened else LoadoutLifecycleState.APPLIED_BEST_EFFORT
        degraded_reason = None if screen_opened else "loadout screen could not be OCR-verified; clicks executed best-effort"
        if not screen_opened:
            notes.append("loadout screen was not OCR-verified")
        result = {
            "requested": requested_loadout,
            "applied": applied,
            "errors": errors,
            "notes": notes,
            "screen_opened": screen_opened,
            "verification_mode": self._flow("verification_mode", "screen_only"),
            "degraded_reason": degraded_reason,
        }
        return LoadoutApplyResponse(state=state, result=result)
