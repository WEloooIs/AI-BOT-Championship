from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
EXE_PATH = BASE_DIR / "pyla_main.exe"
EXTRACTED_DIR = BASE_DIR / "pyla_main.exe_extracted"
PYZ_DIR = EXTRACTED_DIR / "PYZ.pyz_extracted"
INTERNAL_DIR = BASE_DIR / "_internal"
EXTRACT_STATE_PATH = BASE_DIR / "runtime_state" / "original_extract_state.json"
EXTRACTOR_PATH = BASE_DIR / "pyinstxtractor.py"
CUSTOMTKINTER_SOURCE = INTERNAL_DIR / "customtkinter" / "assets"
CUSTOMTKINTER_TARGET = PYZ_DIR / "customtkinter" / "assets"
SCRCPY_SERVER_SOURCE = INTERNAL_DIR / "scrcpy" / "scrcpy-server.jar"
SCRCPY_SERVER_TARGET = PYZ_DIR / "scrcpy" / "scrcpy-server.jar"
MAIN_PYC_PATH = EXTRACTED_DIR / "main.pyc"


def current_extract_state() -> dict[str, int]:
    stat = EXE_PATH.stat()
    return {
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def load_saved_extract_state() -> dict[str, int] | None:
    if not EXTRACT_STATE_PATH.exists():
        return None
    try:
        data = json.loads(EXTRACT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return {
            "size": int(data["size"]),
            "mtime_ns": int(data["mtime_ns"]),
        }
    except Exception:
        return None


def save_extract_state() -> None:
    EXTRACT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXTRACT_STATE_PATH.write_text(
        json.dumps(current_extract_state(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extracted_runtime_ready() -> bool:
    required_paths = (
        MAIN_PYC_PATH,
        PYZ_DIR / "play.pyc",
        PYZ_DIR / "stage_manager.pyc",
        PYZ_DIR / "window_controller.pyc",
        PYZ_DIR / "utils.pyc",
    )
    return all(path.exists() for path in required_paths)


def ensure_extracted_runtime() -> None:
    current_state = current_extract_state()
    saved_state = load_saved_extract_state()
    should_extract = not extracted_runtime_ready() or saved_state != current_state
    if not should_extract:
        return
    if not EXTRACTOR_PATH.exists():
        raise FileNotFoundError(f"Missing extractor: {EXTRACTOR_PATH}")

    if EXTRACTED_DIR.exists():
        shutil.rmtree(EXTRACTED_DIR)

    print("Detected original runtime update. Refreshing extracted modules...")
    subprocess.run(
        [sys.executable, str(EXTRACTOR_PATH), str(EXE_PATH)],
        cwd=BASE_DIR,
        check=True,
    )
    save_extract_state()


def ensure_customtkinter_assets() -> None:
    if CUSTOMTKINTER_TARGET.exists() or not CUSTOMTKINTER_SOURCE.exists():
        return
    CUSTOMTKINTER_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(CUSTOMTKINTER_SOURCE, CUSTOMTKINTER_TARGET, dirs_exist_ok=True)


def ensure_scrcpy_server() -> None:
    if SCRCPY_SERVER_TARGET.exists() or not SCRCPY_SERVER_SOURCE.exists():
        return
    SCRCPY_SERVER_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCRCPY_SERVER_SOURCE, SCRCPY_SERVER_TARGET)


def setup_runtime_imports() -> None:
    os.chdir(BASE_DIR)
    ensure_extracted_runtime()
    ensure_customtkinter_assets()
    ensure_scrcpy_server()

    if str(INTERNAL_DIR) not in sys.path:
        sys.path.append(str(INTERNAL_DIR))

    # Load packaged dependencies before the extracted modules import them.
    import onnxruntime  # noqa: F401
    import ultralytics  # noqa: F401
    import numpy  # noqa: F401
    import cv2  # noqa: F401
    import requests  # noqa: F401
    import PIL  # noqa: F401
    import easyocr  # noqa: F401
    import toml  # noqa: F401
    import termcolor  # noqa: F401
    import adbutils  # noqa: F401
    import shapely  # noqa: F401

    if str(EXTRACTED_DIR) not in sys.path:
        sys.path.insert(0, str(EXTRACTED_DIR))
    if str(PYZ_DIR) not in sys.path:
        sys.path.insert(0, str(PYZ_DIR))


def install_surface_patches() -> None:
    import play  # type: ignore
    import window_controller  # type: ignore
    from state_finder.main import get_state  # type: ignore

    key_coords = getattr(window_controller, "key_coords_dict", None)
    if isinstance(key_coords, dict):
        for new_key, legacy_key in (("F", "M"), ("R", "G"), ("X", "H")):
            if legacy_key in key_coords:
                key_coords[new_key] = key_coords[legacy_key]
        # Center of the bottom-right action button. This avoids hitting the
        # quests/timer stack on the right edge while keeping original flow.
        key_coords["Q"] = (1620, 1000)

    if getattr(play.Play, "_original_surface_patch_installed", False):
        return

    original_init = play.Play.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._surface_keep_last_movement_seconds = 1.15

    def patched_attack(self) -> None:
        self.window_controller.press_key("F")

    def patched_use_gadget(self) -> None:
        print("Using gadget")
        self.window_controller.press_key("R")

    def patched_use_hypercharge(self) -> None:
        print("Using hypercharge")
        self.window_controller.press_key("X")

    def patched_use_super(self) -> None:
        print("Using super")
        self.window_controller.press_key("E")

    def patched_main(self, frame, brawler):
        current_time = time.time()
        data = self.get_main_data(frame)

        if self.should_detect_walls and current_time - self.time_since_walls_checked > self.walls_treshold:
            tile_data = self.get_tile_data(frame)
            walls = self.process_tile_data(tile_data)
            self.time_since_walls_checked = current_time
            self.last_walls_data = walls
            data["wall"] = walls
        elif self.keep_walls_in_memory:
            data["wall"] = self.last_walls_data

        data = self.validate_game_data(data)
        self.track_no_detections(data)
        if data:
            self.time_since_player_last_found = time.time()

        if not data:
            keep_seconds = float(getattr(self, "_surface_keep_last_movement_seconds", 1.15) or 1.15)
            last_seen_delta = current_time - float(getattr(self, "time_since_player_last_found", current_time) or current_time)
            if last_seen_delta <= keep_seconds:
                last_movement = str(getattr(self, "last_movement", "") or "").lower()
                if last_movement:
                    self.do_movement(last_movement)
            elif last_seen_delta > 1.0:
                self.window_controller.keys_up(list("wasd"))

            self.time_since_different_movement = time.time()
            if current_time - self.time_since_last_proceeding > self.no_detection_proceed_delay:
                current_state = get_state(frame)
                if current_state != "match":
                    self.time_since_last_proceeding = current_time
                else:
                    print("haven't detected the player in a while proceeding")
                    # Never press Q here: in matchmaking it maps to Exit.
                    self.window_controller.press_key("F")
                    self.time_since_last_proceeding = current_time
            return

        self.time_since_last_proceeding = time.time()

        self.is_hypercharge_ready = False
        if current_time - self.time_since_hypercharge_checked > self.hypercharge_treshold:
            self.is_hypercharge_ready = self.check_if_hypercharge_ready(frame)
            self.time_since_hypercharge_checked = current_time

        self.is_gadget_ready = False
        if current_time - self.time_since_gadget_checked > self.gadget_treshold:
            self.is_gadget_ready = self.check_if_gadget_ready(frame)
            self.time_since_gadget_checked = current_time

        self.is_super_ready = False
        if current_time - self.time_since_super_checked > self.super_treshold:
            self.is_super_ready = self.check_if_super_ready(frame)
            self.time_since_super_checked = current_time

        self.loop(brawler, data, current_time)

    play.Play.__init__ = patched_init
    play.Play.attack = patched_attack
    play.Play.use_gadget = patched_use_gadget
    play.Play.use_hypercharge = patched_use_hypercharge
    play.Play.use_super = patched_use_super
    play.Play.main = patched_main
    setattr(play.Play, "_original_surface_patch_installed", True)


def smoke_test() -> int:
    setup_runtime_imports()
    install_surface_patches()

    import window_controller  # type: ignore

    key_coords = getattr(window_controller, "key_coords_dict", {})
    expected = {
        "F": key_coords.get("F"),
        "E": key_coords.get("E"),
        "R": key_coords.get("R"),
        "X": key_coords.get("X"),
        "Q": key_coords.get("Q"),
        "scrcpy_server": SCRCPY_SERVER_TARGET.exists(),
    }
    print(f"original-runtime-smoke-ok {expected}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--smoke" in argv:
        return smoke_test()

    setup_runtime_imports()
    install_surface_patches()
    runpy.run_path(str(MAIN_PYC_PATH), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
