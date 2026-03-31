from __future__ import annotations

import argparse
import inspect
import json
import os
import subprocess
import sys
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
INTERNAL_DIR = BASE_DIR / "_internal"
PYZ_DIR = BASE_DIR / "pyla_main.exe_extracted" / "PYZ.pyz_extracted"
CUSTOMTKINTER_ASSETS = PYZ_DIR / "customtkinter" / "assets"
INTERNAL_CUSTOMTKINTER_ASSETS = INTERNAL_DIR / "customtkinter" / "assets"
SCRCPY_SERVER_TARGET = PYZ_DIR / "scrcpy" / "scrcpy-server.jar"
SCRCPY_SERVER_SOURCE = INTERNAL_DIR / "scrcpy" / "scrcpy-server.jar"
ADB_EXE = INTERNAL_DIR / "adbutils" / "binaries" / "adb.exe"
SCRCPY_REMOTE_PATH = "/data/local/tmp/scrcpy-server.jar"
LATEST_BRAWLER_DATA = BASE_DIR / "latest_brawler_data.json"
PUSH_RUNTIME_DIR = BASE_DIR / "runtime_state" / "push"
GENERAL_CFG = BASE_DIR / "cfg" / "general_config.toml"
OFFICIAL_BRAWL_PACKAGE = "com.supercell.brawlstars"
NULLS_BRAWL_PACKAGE = "daniillnull.nulls.brawlstars"
CLIENT_PACKAGE_MAP = {
    "official": OFFICIAL_BRAWL_PACKAGE,
    "nulls": NULLS_BRAWL_PACKAGE,
}
BASE_GAME_WIDTH = 1920
BASE_GAME_HEIGHT = 1080
SUPPORTED_ASPECT_RATIO = BASE_GAME_WIDTH / BASE_GAME_HEIGHT
SUPPORTED_ASPECT_TOLERANCE = 0.03
SCRCPY_STALE_HARD_TIMEOUT = 4.0
SCRCPY_RECOVERY_MIN_INTERVAL = 1.5
SCRCPY_RECOVERY_MAX_ATTEMPTS = 5
SCRCPY_RECOVERY_WINDOW_SECONDS = 45.0


def ensure_customtkinter_assets() -> None:
    if CUSTOMTKINTER_ASSETS.exists() or not INTERNAL_CUSTOMTKINTER_ASSETS.exists():
        return
    CUSTOMTKINTER_ASSETS.parent.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(INTERNAL_CUSTOMTKINTER_ASSETS):
        relative = Path(root).relative_to(INTERNAL_CUSTOMTKINTER_ASSETS)
        target_root = CUSTOMTKINTER_ASSETS / relative
        target_root.mkdir(parents=True, exist_ok=True)
        for file_name in files:
            source_path = Path(root) / file_name
            target_path = target_root / file_name
            if not target_path.exists():
                target_path.write_bytes(source_path.read_bytes())


def ensure_scrcpy_server() -> None:
    if SCRCPY_SERVER_TARGET.exists() or not SCRCPY_SERVER_SOURCE.exists():
        return
    SCRCPY_SERVER_TARGET.parent.mkdir(parents=True, exist_ok=True)
    SCRCPY_SERVER_TARGET.write_bytes(SCRCPY_SERVER_SOURCE.read_bytes())


def setup_runtime_imports() -> None:
    ensure_customtkinter_assets()
    ensure_scrcpy_server()
    if str(INTERNAL_DIR) not in sys.path:
        sys.path.append(str(INTERNAL_DIR))

    # Preload packaged/native deps before the extracted modules.
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

    if str(PYZ_DIR) not in sys.path:
        sys.path.insert(0, str(PYZ_DIR))


setup_runtime_imports()

import utils  # type: ignore  # noqa: E402
import window_controller  # type: ignore  # noqa: E402
import scrcpy.core as scrcpy_core  # type: ignore  # noqa: E402
from gui.select_brawler import SelectBrawler  # type: ignore  # noqa: E402
from lobby_automation import LobbyAutomation  # type: ignore  # noqa: E402
from play import Play  # type: ignore  # noqa: E402
from stage_manager import StageManager  # type: ignore  # noqa: E402
from state_finder.main import get_state  # type: ignore  # noqa: E402
from championship.runtime.bot_runtime_client import BotRuntimeClient  # noqa: E402
from championship.runtime.loadout_automation import LoadoutAutomation  # noqa: E402
from championship.enums import BotProcessState, BotWorkflowState, CommandLifecycleState, LoadoutLifecycleState  # noqa: E402
from championship.error_codes import (
    BRAWLER_PICK_FAILED,
    COMMAND_TARGET_MISSING,
    LOADOUT_NOT_CONFIRMED,
    MATCHMAKING_NOT_ENTERED,
)  # noqa: E402
from championship.platform import FriendlyBattleSnapshot, get_platform_adapter  # noqa: E402


def safe_int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def resolve_model_path(*candidates: str) -> str:
    models_dir = BASE_DIR / "models"
    for candidate in candidates:
        path = models_dir / candidate
        if path.exists():
            return str(path)
    raise FileNotFoundError(
        f"Could not find any of the required model files in {models_dir}: {', '.join(candidates)}"
    )


def build_championship_brawler_data(brawler_name: str) -> list[dict[str, Any]]:
    return [
        {
            "brawler": brawler_name,
            "push_until": 999999,
            "trophies": 0,
            "wins": 0,
            "type": "wins",
            "automatically_pick": True,
            "win_streak": 0,
        }
    ]


def parse_pick_package_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def load_general_cfg() -> dict[str, Any]:
    if not GENERAL_CFG.exists():
        return {}
    try:
        return tomllib.loads(GENERAL_CFG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_target_client_variant() -> str:
    raw = (
        os.environ.get("PYLA_TARGET_GAME_CLIENT")
        or str(load_general_cfg().get("target_game_client", "")).strip()
        or "official"
    )
    value = raw.lower().strip()
    return value if value in CLIENT_PACKAGE_MAP else "official"


def resolve_current_emulator_name() -> str:
    raw = (
        os.environ.get("PYLA_CURRENT_EMULATOR")
        or str(load_general_cfg().get("current_emulator", "")).strip()
        or ""
    )
    value = raw.strip().lower()
    if any(token in value for token in ("mumu", "netease", "nemu")):
        return "mumu"
    if "bluestacks" in value or "hd-player" in value:
        return "bluestacks"
    if "ldplayer" in value or "dnplayer" in value:
        return "ldplayer"
    if "memu" in value:
        return "memu"
    if "android emulator" in value:
        return "android emulator"
    if "local adb device" in value:
        return "local adb device"
    return value


def resolve_target_package_name() -> str:
    override = os.environ.get("PYLA_TARGET_PACKAGE_OVERRIDE", "").strip()
    if override:
        return override
    return CLIENT_PACKAGE_MAP.get(resolve_target_client_variant(), OFFICIAL_BRAWL_PACKAGE)


def resolve_latest_brawler_data_path() -> Path:
    override = os.environ.get("PYLA_LATEST_BRAWLER_DATA_PATH", "").strip()
    if override:
        return Path(override)
    return LATEST_BRAWLER_DATA


def scale_rect_for_controller(controller, rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    wr = float(getattr(controller, "width_ratio", 1.0) or 1.0)
    hr = float(getattr(controller, "height_ratio", 1.0) or 1.0)
    x1, y1, x2, y2 = rect
    return (
        int(x1 * wr),
        int(y1 * hr),
        int(x2 * wr),
        int(y2 * hr),
    )


def install_resolution_support_patches() -> None:
    original_click_brawl_stars = StageManager.click_brawl_stars

    def patched_click_brawl_stars(self, frame):
        screenshot = frame.crop(scale_rect_for_controller(self.window_controller, (50, 4, 900, 31)))
        if self.brawl_stars_icon is None:
            self.brawl_stars_icon = utils.load_image(
                "state_finder/images_to_detect/brawl_stars_icon.png",
                self.window_controller.scale_factor,
            )
        detection = utils.find_template_center(screenshot, self.brawl_stars_icon)
        if detection:
            x, y = detection
            self.window_controller.click(x + 50, y, already_include_ratio=True)
            return
        return original_click_brawl_stars(self, frame)

    StageManager.click_brawl_stars = patched_click_brawl_stars


def install_runtime_control_layout_patch() -> None:
    key_coords = getattr(window_controller, "key_coords_dict", None)
    if isinstance(key_coords, dict):
        for new_key, legacy_key in (("F", "M"), ("R", "G"), ("X", "H")):
            if legacy_key in key_coords:
                key_coords[new_key] = key_coords[legacy_key]
        # Q is reserved for lobby/end-screen continue and should target the
        # center of the bottom-right action button, not the quests/timer area.
        key_coords["Q"] = (1620, 1000)

    if getattr(Play, "_pyla_control_layout_patch_installed", False):
        return

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

    Play.attack = patched_attack
    Play.use_gadget = patched_use_gadget
    Play.use_hypercharge = patched_use_hypercharge
    Play.use_super = patched_use_super
    setattr(Play, "_pyla_control_layout_patch_installed", True)


def install_scrcpy_frame_guard_patch() -> None:
    if getattr(window_controller.WindowController, "_pyla_stale_guard_installed", False):
        return

    original_screenshot = window_controller.WindowController.screenshot

    def guarded_screenshot(self, *args, **kwargs):
        image = original_screenshot(self, *args, **kwargs)
        last_frame_time = float(getattr(self, "last_frame_time", 0.0) or 0.0)
        if last_frame_time > 0.0:
            age = time.time() - last_frame_time
            if age > SCRCPY_STALE_HARD_TIMEOUT:
                raise ConnectionError(
                    f"scrcpy frame stale for {age:.1f}s; transport recovery required"
                )
        return image

    window_controller.WindowController.screenshot = guarded_screenshot
    setattr(window_controller.WindowController, "_pyla_stale_guard_installed", True)


def resolve_scrcpy_target_serial(device: Any = None) -> str:
    if isinstance(device, str):
        return device.strip()
    serial = str(getattr(device, "serial", "") or "").strip()
    if serial:
        return serial
    return os.environ.get("PYLA_INSTANCE_SERIAL", "").strip()


def is_emulator_transport_serial(serial: str) -> bool:
    return serial.startswith("127.0.0.1:") or serial.startswith("emulator-")


def resolve_scrcpy_profile(device: Any = None) -> dict[str, Any]:
    emulator = resolve_current_emulator_name()
    serial = resolve_scrcpy_target_serial(device)

    if emulator == "mumu":
        return {
            "max_width": 960,
            "bitrate": 1_500_000,
            "max_fps": 15,
            "connection_timeout": 5000,
            "encoder_name": "OMX.google.h264.encoder",
            "profile_name": "mumu_safe",
        }
    if is_emulator_transport_serial(serial):
        return {
            "max_width": 1024,
            "bitrate": 2_500_000,
            "max_fps": 20,
            "connection_timeout": 5000,
            "encoder_name": None,
            "profile_name": "emulator_safe",
        }
    return {
        "max_width": 0,
        "bitrate": 8_000_000,
        "max_fps": 0,
        "connection_timeout": 3000,
        "encoder_name": None,
        "profile_name": "default",
    }


def install_scrcpy_client_profile_patch() -> None:
    if getattr(scrcpy_core.Client, "_pyla_profile_patch_installed", False):
        return

    original_init = scrcpy_core.Client.__init__
    signature = inspect.signature(original_init)

    def patched_init(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        target_device = bound.arguments.get("device")
        target_serial = resolve_scrcpy_target_serial(target_device)
        profile = resolve_scrcpy_profile(target_device)

        if int(bound.arguments.get("max_width", 0) or 0) == 0 and profile["max_width"] > 0:
            bound.arguments["max_width"] = profile["max_width"]
        if int(bound.arguments.get("bitrate", 0) or 0) == 8_000_000:
            bound.arguments["bitrate"] = profile["bitrate"]
        if int(bound.arguments.get("max_fps", 0) or 0) == 0 and profile["max_fps"] > 0:
            bound.arguments["max_fps"] = profile["max_fps"]
        if int(bound.arguments.get("connection_timeout", 0) or 0) == 3000:
            bound.arguments["connection_timeout"] = profile["connection_timeout"]
        if bound.arguments.get("encoder_name") is None and profile.get("encoder_name"):
            bound.arguments["encoder_name"] = profile["encoder_name"]

        original_init(*bound.args, **bound.kwargs)
        print(
            "scrcpy profile:"
            f" name={profile['profile_name']},"
            f" serial={target_serial or 'default'},"
            f" max_width={self.max_width or 0},"
            f" bitrate={self.bitrate},"
            f" max_fps={self.max_fps or 0},"
            f" connection_timeout={self.connection_timeout},"
            f" encoder={self.encoder_name or 'auto'}"
        )

    scrcpy_core.Client.__init__ = patched_init
    setattr(scrcpy_core.Client, "_pyla_profile_patch_installed", True)


def validate_runtime_resolution(controller) -> tuple[int, int]:
    frame = controller.screenshot()
    width = int(getattr(controller, "width", 0) or getattr(frame, "width", 0))
    height = int(getattr(controller, "height", 0) or getattr(frame, "height", 0))
    if width <= 0 or height <= 0:
        print("Resolution check warning: could not determine runtime frame size.")
        return (0, 0)

    aspect = width / height if height else 0.0
    aspect_delta = abs(aspect - SUPPORTED_ASPECT_RATIO)
    print(
        "Runtime frame size detected: "
        f"{width}x{height} (wr={getattr(controller, 'width_ratio', 1.0):.3f}, "
        f"hr={getattr(controller, 'height_ratio', 1.0):.3f})"
    )
    if aspect_delta > SUPPORTED_ASPECT_TOLERANCE:
        print(
            "Resolution warning: bot is calibrated for 16:9 layouts. "
            f"Current aspect ratio {aspect:.3f} may cause detection drift."
        )
    elif (width, height) != (BASE_GAME_WIDTH, BASE_GAME_HEIGHT):
        print(
            "Resolution support active: using scaled controls for non-FullHD runtime "
            f"({width}x{height})."
        )
    return (width, height)


install_resolution_support_patches()
install_runtime_control_layout_patch()
install_scrcpy_frame_guard_patch()
install_scrcpy_client_profile_patch()


def apply_runtime_overrides(instance_serial: str | None) -> None:
    original_loader = utils.load_toml_as_dict

    def patched_loader(path: str):
        data = original_loader(path)
        if not isinstance(data, dict):
            return data
        override_port = os.environ.get("PYLA_EMULATOR_PORT")
        normalized = path.replace("\\", "/")
        if override_port and normalized.endswith("cfg/general_config.toml"):
            data = dict(data)
            try:
                data["emulator_port"] = int(override_port)
            except ValueError:
                pass
        return data

    utils.load_toml_as_dict = patched_loader
    window_controller.load_toml_as_dict = patched_loader

    if instance_serial:
        try:
            window_controller.adb.connect(instance_serial)
        except Exception:
            pass

        def device_list_override():
            try:
                return [window_controller.adb.device(serial=instance_serial)]
            except TypeError:
                return [window_controller.adb.device(instance_serial)]

        window_controller.adb.device_list = device_list_override


def safe_run(command: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return subprocess.CompletedProcess(command, 124, stdout, stderr or f"timeout after {timeout}s")


def apply_push_runtime_state_overrides() -> Path:
    target_file = resolve_latest_brawler_data_path()
    target_file.parent.mkdir(parents=True, exist_ok=True)

    def save_brawler_data_local(data):
        target_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    utils.save_brawler_data = save_brawler_data_local
    return target_file


def run_adb_cli(serial: str | None, *args: str, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    command = [str(ADB_EXE)]
    if serial:
        command.extend(["-s", serial])
    command.extend(args)
    return safe_run(command, timeout=timeout)


def ensure_adb_cli_transport(instance_serial: str, *, reconnect: bool = False) -> None:
    if reconnect:
        try:
            run_adb_cli(None, "disconnect", instance_serial, timeout=5)
        except Exception:
            pass
        time.sleep(0.4)
    connect_result = run_adb_cli(None, "connect", instance_serial, timeout=8)
    if connect_result.returncode != 0:
        raise ConnectionError(f"adb connect failed for {instance_serial}: {connect_result.stdout or connect_result.stderr}")
    wait_result = run_adb_cli(instance_serial, "wait-for-device", "shell", "echo", "ok", timeout=20)
    if wait_result.returncode != 0 or "ok" not in wait_result.stdout:
        raise ConnectionError(
            f"adb wait-for-device shell failed for {instance_serial}: "
            f"{wait_result.stdout or wait_result.stderr}"
        )


def deploy_scrcpy_server_via_adb_cli(instance_serial: str) -> None:
    attempts: list[str] = []
    for attempt in range(1, 4):
        reconnect = attempt > 1
        try:
            ensure_adb_cli_transport(instance_serial, reconnect=reconnect)
            mkdir_result = run_adb_cli(instance_serial, "shell", "mkdir", "-p", "/data/local/tmp", timeout=15)
            if mkdir_result.returncode != 0:
                raise ConnectionError(mkdir_result.stdout or mkdir_result.stderr or "mkdir failed")
            push_result = run_adb_cli(
                instance_serial,
                "push",
                str(SCRCPY_SERVER_SOURCE),
                SCRCPY_REMOTE_PATH,
                timeout=30,
            )
            if push_result.returncode != 0:
                raise ConnectionError(push_result.stdout or push_result.stderr or "adb push failed")
            verify_result = run_adb_cli(instance_serial, "shell", "ls", SCRCPY_REMOTE_PATH, timeout=15)
            if verify_result.returncode != 0 or "scrcpy-server.jar" not in verify_result.stdout:
                raise ConnectionError(verify_result.stdout or verify_result.stderr or "remote jar verify failed")
            return
        except Exception as exc:
            attempts.append(f"attempt[{attempt}]={type(exc).__name__}:{exc}")
            time.sleep(0.8)
    detail = "; ".join(attempts) or "no deploy attempts recorded"
    raise ConnectionError(f"Failed to deploy scrcpy-server.jar via adb CLI for {instance_serial}: {detail}")


def install_scrcpy_deploy_patch(default_serial: str | None) -> None:
    if getattr(scrcpy_core.Client, "_pyla_cli_push_patch_installed", False):
        return

    def patched_deploy_server(self) -> None:
        serial = str(getattr(getattr(self, "device", None), "serial", "") or default_serial or "").strip()
        if not serial:
            raise ConnectionError("Scrcpy deploy patch could not resolve target serial.")
        deploy_scrcpy_server_via_adb_cli(serial)
        commands = [
            f"CLASSPATH={SCRCPY_REMOTE_PATH}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            "2.4",
            "log_level=info",
            f"max_size={self.max_width}",
            f"max_fps={self.max_fps}",
            f"video_bit_rate={self.bitrate}",
            "tunnel_forward=true",
            "send_frame_meta=false",
            "control=true",
            "audio=false",
            "show_touches=false",
            "stay_awake=false",
            "power_off_on_close=false",
            "clipboard_autosync=false",
        ]
        encoder_name = str(getattr(self, "encoder_name", "") or "").strip()
        if encoder_name:
            commands.append(f"video_encoder={encoder_name}")
        print("scrcpy server command: " + " ".join(commands[4:]))
        self._Client__server_stream = self.device.shell(commands, stream=True)
        self._Client__server_stream.read(10)

    scrcpy_core.Client._Client__deploy_server = patched_deploy_server
    setattr(scrcpy_core.Client, "_pyla_cli_push_patch_installed", True)


def validate_adb_transport(instance_serial: str | None) -> None:
    if not instance_serial:
        return
    adb = window_controller.adb
    attempts: list[str] = []
    for attempt in range(1, 4):
        try:
            try:
                adb.connect(instance_serial)
            except Exception as exc:
                attempts.append(f"connect[{attempt}]={exc}")
            device = adb.device(serial=instance_serial)
            response = device.shell("echo ok").strip()
            if response == "ok":
                return
            attempts.append(f"shell[{attempt}]=unexpected:{response!r}")
        except Exception as exc:
            attempts.append(f"shell[{attempt}]={type(exc).__name__}:{exc}")
            try:
                adb.disconnect(instance_serial)
            except Exception:
                pass
            time.sleep(0.6)
            continue
    details = "; ".join(attempts) or "no adb shell response"
    raise ConnectionError(
        "ADB transport is unstable for "
        f"{instance_serial}. connect succeeds but adb shell/sync does not work ({details}). "
        "This emulator instance is not ready for scrcpy. Restart the instance or fix its ADB transport first."
    )


def apply_championship_data_overrides(bot_id: str | None) -> None:
    if not bot_id:
        return
    target_file = BASE_DIR / "championship_data" / "runtime" / f"{bot_id}_latest.json"
    target_file.parent.mkdir(parents=True, exist_ok=True)

    def save_brawler_data_local(data):
        target_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    utils.save_brawler_data = save_brawler_data_local


class RuntimeReporter:
    def __init__(
        self,
        coordinator_url: str | None,
        *,
        bot_id: str | None = None,
        team_id: str | None = None,
        instance_id: str | None = None,
        match_id: str | None = None,
        match_context_version: int = 0,
        command_id: str | None = None,
        platform: str | None = None,
    ) -> None:
        self.client = BotRuntimeClient(coordinator_url) if coordinator_url else None
        self.bot_id = bot_id
        self.team_id = team_id
        self.instance_id = instance_id
        self.match_id = match_id
        self.match_context_version = match_context_version
        self.command_id = command_id
        self.platform = platform

    @property
    def enabled(self) -> bool:
        return self.client is not None and self.bot_id is not None

    def _base_payload(self, command_id: str | None = None) -> dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "team_id": self.team_id,
            "instance_id": self.instance_id,
            "match_id": self.match_id,
            "match_context_version": self.match_context_version,
            "command_id": command_id if command_id is not None else self.command_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "platform": self.platform,
        }

    def heartbeat(
        self,
        *,
        workflow_state: str,
        process_state: str,
        selected_brawler: str | None,
        extras: dict[str, Any] | None = None,
        command_id: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        payload = self._base_payload(command_id)
        payload.update(
            {
                "workflow_state": workflow_state,
                "process_state": process_state,
                "selected_brawler": selected_brawler,
                "active_pid": os.getpid(),
                "extras": extras or {},
            }
        )
        self.client.post("/api/bots/heartbeat", payload)

    def pick_started(self, brawler: str, *, command_id: str | None = None, pick_package: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        payload = self._base_payload(command_id)
        payload["brawler"] = brawler
        if pick_package is not None:
            payload["pick_package"] = pick_package
        self.client.post("/api/bots/pick-started", payload)

    def pick_confirmed(
        self,
        brawler: str,
        *,
        command_id: str | None = None,
        pick_package: dict[str, Any] | None = None,
        loadout_state: str | None = None,
        loadout_result: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        payload = self._base_payload(command_id)
        payload["brawler"] = brawler
        if pick_package is not None:
            payload["pick_package"] = pick_package
        if loadout_state is not None:
            payload["loadout_state"] = loadout_state
        if loadout_result is not None:
            payload["loadout_result"] = loadout_result
        self.client.post("/api/bots/pick-confirmed", payload)

    def pick_failed(
        self,
        brawler: str,
        error: str,
        *,
        command_id: str | None = None,
        failure_code: str = BRAWLER_PICK_FAILED,
        pick_package: dict[str, Any] | None = None,
        loadout_state: str | None = None,
        loadout_result: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        payload = self._base_payload(command_id)
        payload.update({"brawler": brawler, "failure_code": failure_code, "failure_reason": error})
        if pick_package is not None:
            payload["pick_package"] = pick_package
        if loadout_state is not None:
            payload["loadout_state"] = loadout_state
        if loadout_result is not None:
            payload["loadout_result"] = loadout_result
        self.client.post("/api/bots/pick-failed", payload)

    def runtime_error(self, error_code: str, error_reason: str, *, command_id: str | None = None) -> None:
        if not self.enabled:
            return
        payload = self._base_payload(command_id)
        payload.update({"error_code": error_code, "error_reason": error_reason})
        self.client.post("/api/bots/error", payload)

    def fetch_next_command(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        payload = self._base_payload(None)
        result = self.client.post("/api/bots/commands/next", payload)
        if not result.get("ok"):
            return None
        return result.get("command")

    def update_command(
        self,
        command_id: str,
        state: str,
        *,
        failure_code: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        payload = {
            "command_id": command_id,
            "state": state,
            "timestamp": datetime.now(UTC).isoformat(),
            "failure_code": failure_code,
            "failure_reason": failure_reason,
        }
        self.client.post("/api/commands/update", payload)


class ReportingLobbyAutomation(LobbyAutomation):
    def __init__(self, window_controller_obj, reporter: RuntimeReporter | None) -> None:
        super().__init__(window_controller_obj)
        self.reporter = reporter

    def select_brawler(
        self,
        brawler_name,
        *,
        command_id: str | None = None,
        pick_package: dict[str, Any] | None = None,
        report_result: bool = True,
        loadout_state: str | None = None,
        loadout_result: dict[str, Any] | None = None,
    ):
        if self.reporter:
            self.reporter.pick_started(brawler_name, command_id=command_id, pick_package=pick_package)
        try:
            result = super().select_brawler(brawler_name)
        except Exception as exc:
            if self.reporter:
                self.reporter.pick_failed(
                    brawler_name,
                    str(exc),
                    command_id=command_id,
                    failure_code=BRAWLER_PICK_FAILED,
                    pick_package=pick_package,
                )
            raise
        if self.reporter and report_result:
            self.reporter.pick_confirmed(
                brawler_name,
                command_id=command_id,
                pick_package=pick_package,
                loadout_state=loadout_state,
                loadout_result=loadout_result,
            )
        return result


class BalancedPlay(Play):
    def __init__(self, main_info_model: str, tile_detector_model: str, window_controller_obj) -> None:
        super().__init__(main_info_model, tile_detector_model, window_controller_obj)
        self.cached_main_data: dict[str, Any] | None = None
        self.last_main_detection_at = 0.0
        self.main_detection_interval_active = 0.09
        self.main_detection_interval_search = 0.05
        self.last_had_game_data = False
        self.search_movement_pattern = ("d", "sd", "s", "sa", "a", "wa", "w", "wd")
        self.search_movement_index = 0
        self.search_movement = "d"
        self.last_search_movement_at = 0.0
        self.search_movement_change_interval = 0.85
        self.no_detection_keep_moving_seconds = 1.35

    def _copy_cached_data(self) -> Any:
        if isinstance(self.cached_main_data, dict):
            return dict(self.cached_main_data)
        return self.cached_main_data

    def _should_refresh_main_data(self, current_time: float) -> bool:
        if self.cached_main_data is None:
            return True
        data = self.cached_main_data
        has_core_data = isinstance(data, dict) and bool(data.get("player") or data.get("enemy"))
        interval = self.main_detection_interval_active if has_core_data else self.main_detection_interval_search
        return current_time - self.last_main_detection_at >= interval

    def can_attack_through_walls(self, brawler, skill_type, brawlers_info=None):
        if not brawler:
            return False
        if skill_type not in ("attack", "super"):
            return False
        try:
            return super().can_attack_through_walls(brawler, skill_type, brawlers_info)
        except KeyError:
            return False

    def _advance_search_movement(self) -> str:
        candidate = self.search_movement_pattern[self.search_movement_index % len(self.search_movement_pattern)]
        self.search_movement_index = (self.search_movement_index + 1) % len(self.search_movement_pattern)
        last_movement = str(getattr(self, "last_movement", "") or "").lower()
        if last_movement and candidate == self.reverse_movement(last_movement):
            candidate = self.search_movement_pattern[self.search_movement_index % len(self.search_movement_pattern)]
            self.search_movement_index = (self.search_movement_index + 1) % len(self.search_movement_pattern)
        self.search_movement = candidate
        return candidate

    def _apply_no_detection_movement(self, current_time: float) -> None:
        last_movement = str(getattr(self, "last_movement", "") or "").lower()
        if last_movement and current_time - self.time_since_player_last_found <= self.no_detection_keep_moving_seconds:
            movement = self.unstuck_movement_if_needed(last_movement, current_time)
            self.do_movement(movement)
            return

        if current_time - self.last_search_movement_at >= self.search_movement_change_interval:
            self._advance_search_movement()
            self.last_search_movement_at = current_time

        movement = self.unstuck_movement_if_needed(self.search_movement, current_time)
        self.do_movement(movement)

    def main(
        self,
        frame,
        brawler: str,
        *,
        known_state: str = "match",
        allow_proceed: bool = True,
    ) -> bool:
        current_time = time.time()
        self.current_brawler = brawler

        if self._should_refresh_main_data(current_time):
            data = self.get_main_data(frame)
            self.cached_main_data = data
            self.last_main_detection_at = current_time
        else:
            data = self._copy_cached_data()

        if self.should_detect_walls and current_time - self.time_since_walls_checked > self.walls_treshold:
            tile_data = self.get_tile_data(frame)
            walls = self.process_tile_data(tile_data)
            self.time_since_walls_checked = current_time
            self.last_walls_data = walls
            if isinstance(data, dict):
                data["wall"] = walls
        elif self.keep_walls_in_memory and isinstance(data, dict):
            data["wall"] = self.last_walls_data

        data = self.validate_game_data(data)
        self.track_no_detections(data)

        if data:
            self.time_since_player_last_found = time.time()
            self.time_since_last_proceeding = time.time()
            self.last_had_game_data = True
            self.last_search_movement_at = 0.0
        else:
            self.last_had_game_data = False
            self.time_since_different_movement = time.time()
            if allow_proceed:
                self._apply_no_detection_movement(current_time)
            elif current_time - self.time_since_player_last_found > 1.0:
                self.window_controller.keys_up(list("wasd"))
            if allow_proceed and current_time - self.time_since_last_proceeding > self.no_detection_proceed_delay:
                if known_state != "match":
                    self.time_since_last_proceeding = current_time
                else:
                    print("haven't detected the player in a while proceeding")
                    self.window_controller.press_key("F")
                    self.time_since_last_proceeding = current_time
            return False

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
        return True


class BalancedStageManager(StageManager):
    def __init__(self, brawlers_data, lobby_automator, window_controller_obj, *, target_client_variant: str, target_package_name: str) -> None:
        super().__init__(brawlers_data, lobby_automator, window_controller_obj)
        thresholds = utils.load_toml_as_dict("./cfg/time_tresholds.toml")
        self.fast_requeue_delay = float(thresholds.get("fast_requeue_delay", 0.45))
        self.matchmaking_guard_seconds = float(thresholds.get("matchmaking_guard_seconds", 45.0))
        self.matchmaking_guard_until = 0.0
        self.last_fast_action_at = 0.0
        self.end_screen_entered_at = 0.0
        self.end_result_recorded = False
        self.last_end_result_check_at = 0.0
        self.last_play_store_click_at = 0.0
        self.target_client_variant = target_client_variant
        self.target_package_name = target_package_name
        self.last_initial_brawler_pick_attempt_at = 0.0
        self.initial_brawler_pick_retry_seconds = 8.0
        self.initial_brawler_pick_confirmed_for: str | None = None
        self._observer_state_brawler: str | None = None

    def _sync_trophy_observer_state(self, entry: dict[str, Any], *, force: bool = False) -> None:
        current_brawler = str(entry.get("brawler") or "").strip()
        if not current_brawler:
            return

        should_reset_for_brawler = force or self._observer_state_brawler != current_brawler
        if should_reset_for_brawler:
            self.Trophy_observer.current_trophies = safe_int(entry.get("trophies"), 0)
            self.Trophy_observer.current_wins = safe_int(entry.get("wins"), 0)
            setattr(self.Trophy_observer, "win_streak", safe_int(entry.get("win_streak"), 0))
            self._observer_state_brawler = current_brawler
            return

        if getattr(self.Trophy_observer, "current_trophies", None) is None:
            self.Trophy_observer.current_trophies = safe_int(entry.get("trophies"), 0)
        if getattr(self.Trophy_observer, "current_wins", None) is None:
            self.Trophy_observer.current_wins = safe_int(entry.get("wins"), 0)
        if getattr(self.Trophy_observer, "win_streak", None) is None:
            setattr(self.Trophy_observer, "win_streak", safe_int(entry.get("win_streak"), 0))

    def on_state_change(self, previous_state: str | None, current_state: str) -> None:
        if current_state != "end":
            self.end_screen_entered_at = 0.0
            self.end_result_recorded = False
            self.last_end_result_check_at = 0.0
        if current_state != "play_store":
            self.last_play_store_click_at = 0.0

    def is_matchmaking_guard_active(self, current_time: float | None = None) -> bool:
        if current_time is None:
            current_time = time.time()
        return current_time < self.matchmaking_guard_until

    def clear_matchmaking_guard(self) -> None:
        self.matchmaking_guard_until = 0.0

    def _current_push_snapshot(self) -> tuple[dict[str, Any], str, int, int]:
        entry = self.brawlers_pick_data[0]
        self._sync_trophy_observer_state(entry)
        push_type = entry.get("type", "trophies")
        if push_type not in ("trophies", "wins"):
            push_type = "trophies"

        current_values = {
            "trophies": self.Trophy_observer.current_trophies,
            "wins": self.Trophy_observer.current_wins,
        }
        current_value = safe_int(current_values.get(push_type), 0 if push_type == "wins" else 0)
        default_target = 300 if push_type == "wins" else 1000
        target_value = safe_int(entry.get("push_until"), default_target)
        return entry, push_type, current_value, target_value

    def _current_target_completed(self) -> bool:
        _, _, current_value, target_value = self._current_push_snapshot()
        return current_value >= target_value

    def _ensure_initial_brawler_selected(self) -> bool:
        if not self.brawlers_pick_data:
            return True
        current_entry = self.brawlers_pick_data[0]
        current_brawler = str(current_entry.get("brawler") or "").strip()
        if not current_brawler:
            return True
        if not bool(current_entry.get("automatically_pick")):
            return True
        if self.initial_brawler_pick_confirmed_for == current_brawler:
            return True

        now = time.time()
        if now - self.last_initial_brawler_pick_attempt_at < self.initial_brawler_pick_retry_seconds:
            return False
        self.last_initial_brawler_pick_attempt_at = now
        print(f"Auto-selecting configured starting brawler: {current_brawler}")
        try:
            self.Lobby_automation.select_brawler(current_brawler)
        except Exception as exc:
            print(f"Auto-select of starting brawler failed: {exc}")
            return False
        self.initial_brawler_pick_confirmed_for = current_brawler
        return True

    def start_game(self, data) -> None:
        if not self._current_target_completed():
            if not self._ensure_initial_brawler_selected():
                return

        if self._current_target_completed():
            super().start_game(data)
            return

        now = time.time()
        if now - self.last_fast_action_at < self.fast_requeue_delay:
            return

        entry, push_type, current_value, target_value = self._current_push_snapshot()
        self.window_controller.keys_up(list("wasd"))
        self.window_controller.press_key("Q")
        self.last_fast_action_at = now
        self.matchmaking_guard_until = now + self.matchmaking_guard_seconds
        print(
            "Fast requeue: pressed Q from lobby "
            f"for {entry.get('brawler', '?')} ({push_type} {current_value}/{target_value})"
        )

    def end_game(self) -> None:
        screenshot = self.window_controller.screenshot()
        current_state = get_state(screenshot)
        if current_state != "end":
            if self.end_screen_entered_at:
                print("Game has ended", current_state)
            self.end_screen_entered_at = 0.0
            self.end_result_recorded = False
            return

        now = time.time()
        if not self.end_screen_entered_at:
            self.end_screen_entered_at = now

        entry, push_type, _, _ = self._current_push_snapshot()
        self._sync_trophy_observer_state(entry)
        if (
            not self.end_result_recorded
            and now - self.end_screen_entered_at >= 1.0
            and now - self.last_end_result_check_at >= 1.0
        ):
            found_game_result = self.Trophy_observer.find_game_result(
                screenshot,
                current_brawler=entry["brawler"],
            )
            self.last_end_result_check_at = now
            if found_game_result:
                self.end_result_recorded = True
                current_values = {
                    "trophies": self.Trophy_observer.current_trophies,
                    "wins": self.Trophy_observer.current_wins,
                }
                entry[push_type] = safe_int(current_values.get(push_type), 0)
                entry["trophies"] = safe_int(self.Trophy_observer.current_trophies, safe_int(entry.get("trophies"), 0))
                entry["wins"] = safe_int(self.Trophy_observer.current_wins, safe_int(entry.get("wins"), 0))
                entry["win_streak"] = safe_int(getattr(self.Trophy_observer, "win_streak", None), safe_int(entry.get("win_streak"), 0))
                utils.save_brawler_data(self.brawlers_pick_data)
                if self._current_target_completed() and len(self.brawlers_pick_data) <= 1:
                    super().end_game()
                    return

        if now - self.last_fast_action_at < self.fast_requeue_delay:
            return

        self.window_controller.press_key("Q")
        self.last_fast_action_at = now
        print("Fast post-match continue: pressed Q")

    def maybe_recover_from_home(self, frame) -> None:
        now = time.time()
        if self.is_matchmaking_guard_active(now):
            print("Matchmaking guard active: skipping play_store/home recovery.")
            return
        if now - self.last_play_store_click_at < 3.0:
            return
        self.last_play_store_click_at = now
        try:
            current_app = self.window_controller.device.app_current()
        except Exception:
            current_app = {}
        current_package = str((current_app or {}).get("package") or "").strip()
        if current_package == self.target_package_name:
            return
        try:
            self.window_controller.keys_up(list("wasd"))
            self.window_controller.device.app_start(self.target_package_name)
            print(
                "Recovery: starting configured game package "
                f"{self.target_package_name} ({self.target_client_variant})"
            )
            return
        except Exception as exc:
            print(
                "Recovery warning: failed to start configured game package "
                f"{self.target_package_name} ({self.target_client_variant}): {exc}"
            )
        print("Recovery fallback: clicking detected Brawl Stars icon from emulator home screen")
        self.click_brawl_stars(frame)


class ChampionshipRuntimeController:
    def __init__(
        self,
        runner,
        reporter: RuntimeReporter,
        *,
        platform_name: str,
        target_brawler: str,
        is_host: bool,
    ) -> None:
        self.runner = runner
        self.reporter = reporter
        self.adapter = get_platform_adapter(platform_name)
        self.target_brawler = target_brawler
        self.current_pick_package: dict[str, Any] = {"brawler": target_brawler}
        self.is_host = is_host
        self.pick_confirmed = False
        self.pending_pick_command_id = reporter.command_id
        self.active_start_command: dict[str, Any] | None = None
        self.completed_command_ids: set[str] = set()
        self.last_pick_attempt_at = 0.0
        self.last_command_poll_at = 0.0
        self.last_snapshot_at = 0.0
        self.last_snapshot_state: str | None = None
        self.last_had_game_data = False
        self.current_loadout_state = str(LoadoutLifecycleState.NOT_REQUESTED)
        self.current_loadout_result: dict[str, Any] = {}
        self.current_snapshot = FriendlyBattleSnapshot(
            adapter_name=self.adapter.name,
            base_state="unknown",
            workflow_state=str(BotWorkflowState.NOT_READY),
            lobby_established=False,
            expected_lobby_state=False,
            friendly_lobby_detected=False,
            start_button_visible=False,
            matchmaking_entered=False,
            match_started_confirmed=False,
            queue_exit_visible=False,
        )

    def _refresh_snapshot(self, frame, state: str, had_game_data: bool, now: float) -> FriendlyBattleSnapshot:
        should_refresh = (
            self.last_snapshot_state != state
            or had_game_data != self.last_had_game_data
            or now - self.last_snapshot_at >= self.adapter.ocr_interval_seconds
        )
        if should_refresh:
            workflow_state = self.workflow_state_for_report(state, now)
            self.current_snapshot = self.adapter.analyze_runtime_state(
                frame,
                base_state=state,
                workflow_state=str(workflow_state),
                guard_active=self.runner.stage_manager.is_matchmaking_guard_active(now),
                had_game_data=had_game_data,
                is_host=self.is_host or bool(self.active_start_command),
            )
            self.last_snapshot_at = now
            self.last_snapshot_state = state
            self.last_had_game_data = had_game_data
        return self.current_snapshot

    def _ensure_lobby(self) -> bool:
        for _ in range(12):
            frame = self.runner.window_controller.screenshot()
            state = get_state(frame)
            if state == "lobby":
                self.current_snapshot = self.adapter.analyze_runtime_state(
                    frame,
                    base_state=state,
                    workflow_state=str(BotWorkflowState.IN_LOBBY),
                    guard_active=False,
                    had_game_data=False,
                    is_host=self.is_host,
                )
                return True
            if state in {"popup", "shop", "star_drop", "trophy_reward"}:
                self.runner.stage_manager.do_state(state)
            elif state == "play_store":
                self.runner.stage_manager.maybe_recover_from_home(frame)
            else:
                self.runner.window_controller.keys_up(list("wasd"))
                self.runner.window_controller.press_key("Q")
            time.sleep(1.0)
        return False

    def _poll_command(self, now: float) -> None:
        if now - self.last_command_poll_at < 1.0:
            return
        self.last_command_poll_at = now
        command = self.reporter.fetch_next_command()
        if not command:
            return
        command_id = command["command_id"]
        if command_id in self.completed_command_ids:
            return
        if self.active_start_command and self.active_start_command.get("command_id") == command_id:
            return
        if self.pending_pick_command_id == command_id and not self.pick_confirmed:
            return
        command_type = command["command_type"]
        payload = command.get("payload", {})
        if command_type == "assign_pick":
            self.pending_pick_command_id = command_id
            self.current_pick_package = payload.get("pick_package") or self.current_pick_package or {}
            if payload.get("brawler"):
                self.target_brawler = payload["brawler"]
            elif self.current_pick_package.get("brawler"):
                self.target_brawler = str(self.current_pick_package.get("brawler"))
            self.pick_confirmed = False
            self.current_loadout_state = str(LoadoutLifecycleState.NOT_REQUESTED)
            self.current_loadout_result = {}
            return
        if command_type == "start_matchmaking":
            target_host = payload.get("host_bot_id")
            if target_host and target_host != self.reporter.bot_id:
                self.reporter.update_command(
                    command_id,
                    CommandLifecycleState.FAILED,
                    failure_code=COMMAND_TARGET_MISSING,
                    failure_reason="Only the designated host worker can start matchmaking.",
                )
                self.completed_command_ids.add(command_id)
                return
            self.active_start_command = {
                "command_id": command_id,
                "accepted": False,
                "pressed_at": None,
                "host_bot_id": target_host or self.reporter.bot_id,
            }

    def _maybe_execute_pick(self, state: str, now: float) -> None:
        if self.pick_confirmed or not self.pending_pick_command_id or not self.target_brawler:
            return
        if now - self.last_pick_attempt_at < 5.0:
            return
        if state not in {"lobby", "brawler_selection", "popup", "shop", "star_drop", "trophy_reward", "play_store"}:
            return
        self.last_pick_attempt_at = now
        if not self._ensure_lobby():
            return
        try:
            self.runner.lobby_automator.select_brawler(
                self.target_brawler,
                command_id=self.pending_pick_command_id,
                pick_package=self.current_pick_package,
                report_result=False,
            )
        except Exception:
            self.completed_command_ids.add(self.pending_pick_command_id)
            self.pending_pick_command_id = None
            return
        loadout_response = self.runner.loadout_automator.apply_pick_package(self.current_pick_package)
        self.current_loadout_state = str(loadout_response.state)
        self.current_loadout_result = dict(loadout_response.result)
        if loadout_response.state == LoadoutLifecycleState.FAILED:
            self.reporter.pick_failed(
                self.target_brawler,
                loadout_response.error_reason or "Loadout could not be applied.",
                command_id=self.pending_pick_command_id,
                failure_code=loadout_response.error_code or LOADOUT_NOT_CONFIRMED,
                pick_package=self.current_pick_package,
                loadout_state=self.current_loadout_state,
                loadout_result=self.current_loadout_result,
            )
            self.completed_command_ids.add(self.pending_pick_command_id)
            self.pending_pick_command_id = None
            return
        self.reporter.pick_confirmed(
            self.target_brawler,
            command_id=self.pending_pick_command_id,
            pick_package=self.current_pick_package,
            loadout_state=self.current_loadout_state,
            loadout_result=self.current_loadout_result,
        )
        self.pick_confirmed = True
        self.completed_command_ids.add(self.pending_pick_command_id)
        self.pending_pick_command_id = None

    def _maybe_execute_start(self, now: float) -> None:
        if not self.active_start_command:
            return
        command_id = self.active_start_command["command_id"]
        if self.current_snapshot.match_started_confirmed or self.current_snapshot.matchmaking_entered:
            self.reporter.update_command(command_id, CommandLifecycleState.COMPLETED)
            self.completed_command_ids.add(command_id)
            self.active_start_command = None
            return
        if not self.active_start_command["accepted"]:
            self.reporter.update_command(command_id, CommandLifecycleState.ACCEPTED)
            self.active_start_command["accepted"] = True
        if self.active_start_command["pressed_at"] is None:
            if not self.current_snapshot.lobby_established or not self.current_snapshot.expected_lobby_state:
                return
            try:
                self.adapter.perform_start_matchmaking(self.runner.window_controller, self.current_snapshot)
            except Exception as exc:
                self.reporter.update_command(
                    command_id,
                    CommandLifecycleState.FAILED,
                    failure_code=MATCHMAKING_NOT_ENTERED,
                    failure_reason=str(exc),
                )
                self.completed_command_ids.add(command_id)
                self.active_start_command = None
                return
            self.active_start_command["pressed_at"] = now
            self.runner.stage_manager.matchmaking_guard_until = now + self.runner.stage_manager.matchmaking_guard_seconds
            return
        if now - float(self.active_start_command["pressed_at"]) >= self.adapter.start_timeout_seconds:
            self.reporter.update_command(
                command_id,
                CommandLifecycleState.FAILED,
                failure_code=MATCHMAKING_NOT_ENTERED,
                failure_reason="Matchmaking was not entered after the start trigger.",
            )
            self.completed_command_ids.add(command_id)
            self.active_start_command = None

    def update(self, frame, state: str, had_game_data: bool, now: float) -> None:
        self._refresh_snapshot(frame, state, had_game_data, now)
        self._poll_command(now)
        if state != "match":
            self._maybe_execute_pick(state, now)
        if self.pick_confirmed:
            self._maybe_execute_start(now)

    def workflow_state_for_report(self, state: str, now: float) -> str:
        if state == "end":
            return BotWorkflowState.POST_MATCH
        if state == "match":
            return BotWorkflowState.MATCHMAKING if self.runner.stage_manager.is_matchmaking_guard_active(now) else BotWorkflowState.IN_MATCH
        if not self.pick_confirmed:
            return BotWorkflowState.SELECTING_BRAWLER
        if state == "lobby":
            return BotWorkflowState.IN_LOBBY
        return BotWorkflowState.BRAWLER_SELECTED

    def heartbeat_extras(self, state: str) -> dict[str, Any]:
        return {
            "state": state,
            "friendly_flow": self.current_snapshot.to_dict(),
            "championship": {
                "target_brawler": self.target_brawler,
                "pick_package": self.current_pick_package,
                "pick_confirmed": self.pick_confirmed,
                "loadout_state": self.current_loadout_state,
                "loadout_result": self.current_loadout_result,
                "is_host": self.is_host,
                "current_host_authorized": self.is_host or bool(self.active_start_command),
                "pending_pick_command_id": self.pending_pick_command_id,
                "active_start_command_id": (self.active_start_command or {}).get("command_id"),
            },
        }


class BalancedBotRunner:
    def __init__(
        self,
        brawlers_data: list[dict[str, Any]],
        reporter: RuntimeReporter | None = None,
        *,
        platform_name: str | None = None,
        friendly_host: bool = False,
    ) -> None:
        self.brawlers_data = brawlers_data
        self.reporter = reporter
        self.general_config = utils.load_toml_as_dict("./cfg/general_config.toml")
        self.max_ips = max(1, safe_int(self.general_config.get("max_ips"), 26))
        self.target_client_variant = resolve_target_client_variant()
        self.target_package_name = resolve_target_package_name()
        self.window_controller = window_controller.WindowController()
        self.runtime_resolution = validate_runtime_resolution(self.window_controller)
        self.lobby_automator = ReportingLobbyAutomation(self.window_controller, reporter)
        self.loadout_automator = LoadoutAutomation(self.window_controller)
        self.stage_manager = BalancedStageManager(
            brawlers_data,
            self.lobby_automator,
            self.window_controller,
            target_client_variant=self.target_client_variant,
            target_package_name=self.target_package_name,
        )
        self.play = BalancedPlay(
            resolve_model_path("mainInGameModel.onnx"),
            resolve_model_path("wall_detectionv2.onnx", "tileDetector.onnx"),
            self.window_controller,
        )
        self.state: str | None = None
        self.last_state_check_at = 0.0
        self.last_idle_check_at = 0.0
        self.last_non_match_action_at: dict[str, float] = {}
        self.last_long_no_detection_recovery_at = 0.0
        self.last_transport_recovery_at = 0.0
        self.transport_recovery_attempts: list[float] = []
        self.no_detections_action_threshold = 480
        self.last_report_at = 0.0
        self.championship_controller = (
            ChampionshipRuntimeController(
                self,
                reporter,
                platform_name=platform_name or "nulls",
                target_brawler=self._current_brawler(),
                is_host=friendly_host,
            )
            if reporter and reporter.enabled
            else None
        )

    def _rebind_runtime_components(self, new_controller) -> None:
        self.window_controller = new_controller
        self.runtime_resolution = validate_runtime_resolution(self.window_controller)
        self.lobby_automator.window_controller = self.window_controller
        self.loadout_automator.window_controller = self.window_controller
        self.stage_manager.window_controller = self.window_controller
        self.stage_manager.Lobby_automation = self.lobby_automator
        self.play.window_controller = self.window_controller

    def _recover_scrcpy_transport(self, exc: Exception, now: float) -> str:
        self.transport_recovery_attempts = [
            attempt_at
            for attempt_at in self.transport_recovery_attempts
            if now - attempt_at <= SCRCPY_RECOVERY_WINDOW_SECONDS
        ]
        if len(self.transport_recovery_attempts) >= SCRCPY_RECOVERY_MAX_ATTEMPTS:
            print(
                "Recovery failed: scrcpy transport exceeded retry budget "
                f"({len(self.transport_recovery_attempts)} attempts in "
                f"{SCRCPY_RECOVERY_WINDOW_SECONDS:.0f}s)."
            )
            return "failed"
        if now - self.last_transport_recovery_at < SCRCPY_RECOVERY_MIN_INTERVAL:
            print(
                "Recovery warning: scrcpy transport is still within cooldown, "
                f"deferring reconnect ({exc})."
            )
            return "defer"

        self.last_transport_recovery_at = now
        self.transport_recovery_attempts.append(now)
        serial = str(getattr(getattr(self.window_controller, "device", None), "serial", "") or "").strip()
        print(f"Recovery: rebuilding scrcpy/window controller for {serial or 'default device'} after {exc}")
        if self.reporter:
            try:
                self.reporter.runtime_error("SCRCPY_TRANSPORT_STALE", str(exc))
            except Exception:
                pass

        old_controller = self.window_controller
        try:
            old_controller.keys_up(list("wasd"))
        except Exception:
            pass
        for attr_name in ("client", "control", "_client"):
            target = getattr(old_controller, attr_name, None)
            stop_fn = getattr(target, "stop", None)
            if callable(stop_fn):
                try:
                    stop_fn()
                except Exception:
                    pass
        stop_fn = getattr(old_controller, "stop", None)
        if callable(stop_fn):
            try:
                stop_fn()
            except Exception:
                pass

        try:
            if serial:
                ensure_adb_cli_transport(serial, reconnect=True)
            new_controller = window_controller.WindowController()
            self._rebind_runtime_components(new_controller)
            self.state = None
            self.last_state_check_at = 0.0
            print("Recovery: scrcpy/window controller rebuilt successfully.")
            return "recovered"
        except Exception as rebuild_exc:
            print(f"Recovery failed: {rebuild_exc}")
            if self.reporter:
                try:
                    self.reporter.runtime_error("SCRCPY_TRANSPORT_RECOVERY_FAILED", str(rebuild_exc))
                except Exception:
                    pass
            return "failed"

    def _current_brawler(self) -> str:
        return self.stage_manager.brawlers_pick_data[0]["brawler"]

    def _state_check_interval(self) -> float:
        if self.state == "match":
            if self.stage_manager.is_matchmaking_guard_active():
                return 0.45
            return 0.75
        return 0.30

    def _loop_interval(self) -> float:
        if self.state == "match":
            if self.stage_manager.is_matchmaking_guard_active():
                return max(1.0 / self.max_ips, 0.08)
            return 1.0 / self.max_ips
        return 0.16

    def _should_run_idle_check(self, now: float) -> bool:
        return self.state == "lobby" and now - self.last_idle_check_at >= 4.0

    def _maybe_refresh_state(self, frame, now: float) -> None:
        if self.state is not None and now - self.last_state_check_at < self._state_check_interval():
            return

        previous_state = self.state
        self.state = get_state(frame)
        self.last_state_check_at = now

        if previous_state != self.state:
            self.stage_manager.on_state_change(previous_state, self.state)
            print(f"State changed: {previous_state!s} -> {self.state}")

    def _handle_non_match_state(self, frame, now: float) -> None:
        assert self.state is not None

        if self.stage_manager.is_matchmaking_guard_active(now):
            if self.state in {"lobby", "play_store", "popup", "shop", "star_drop", "trophy_reward", "brawler_selection"}:
                return

        if self.state == "lobby":
            if self.championship_controller:
                return
            self.stage_manager.start_game(frame)
            return

        if self.state == "end":
            if self.championship_controller:
                return
            self.stage_manager.end_game()
            return

        if self.state == "play_store":
            self.stage_manager.maybe_recover_from_home(frame)
            return

        action_intervals = {
            "popup": 0.6,
            "shop": 0.8,
            "star_drop": 0.8,
            "trophy_reward": 0.6,
            "brawler_selection": 0.8,
        }
        required_interval = action_intervals.get(self.state)
        if required_interval is None:
            return

        last_action_at = self.last_non_match_action_at.get(self.state, 0.0)
        if now - last_action_at < required_interval:
            return

        self.stage_manager.do_state(self.state)
        self.last_non_match_action_at[self.state] = now

    def _check_for_stale_match(self, now: float) -> None:
        if self.stage_manager.is_matchmaking_guard_active(now):
            return
        if now - self.last_long_no_detection_recovery_at < 30.0:
            return

        stale_detections = []
        for key, last_seen_at in self.play.time_since_detections.items():
            if now - last_seen_at > self.no_detections_action_threshold:
                stale_detections.append(key)
        if not stale_detections:
            return

        self.last_long_no_detection_recovery_at = now
        package_name = self.target_package_name or getattr(window_controller, "BRAWL_STARS_PACKAGE", None)
        print(
            "Recovery: stale match detections "
            f"{stale_detections}, restarting configured game package {package_name} ({self.target_client_variant})"
        )
        try:
            if package_name:
                self.window_controller.device.app_start(package_name)
            self.stage_manager.clear_matchmaking_guard()
        except Exception as exc:  # pragma: no cover - best effort device recovery
            print(f"Recovery failed: {exc}")

    def run(self) -> None:
        while True:
            loop_started_at = time.time()
            now = time.time()
            try:
                frame = self.window_controller.screenshot()
                now = time.time()
                self._maybe_refresh_state(frame, now)
                had_game_data = False

                if self.state == "match":
                    had_game_data = self.play.main(
                        frame,
                        self._current_brawler(),
                        known_state="match",
                        allow_proceed=not self.stage_manager.is_matchmaking_guard_active(now),
                    )
                    if had_game_data:
                        self.stage_manager.clear_matchmaking_guard()
                    self._check_for_stale_match(now)
                else:
                    if self._should_run_idle_check(now):
                        self.lobby_automator.check_for_idle(frame)
                        self.last_idle_check_at = now
                    self._handle_non_match_state(frame, now)

                if self.championship_controller and self.state is not None:
                    self.championship_controller.update(frame, self.state, had_game_data, now)

                if self.reporter and now - self.last_report_at >= 2.0:
                    workflow_state = BotWorkflowState.NOT_READY
                    extras = {"state": self.state}
                    if self.championship_controller and self.state is not None:
                        workflow_state = self.championship_controller.workflow_state_for_report(self.state, now)
                        extras = self.championship_controller.heartbeat_extras(self.state)
                    else:
                        if self.state == "lobby":
                            workflow_state = BotWorkflowState.IN_LOBBY
                        elif self.state == "match":
                            workflow_state = BotWorkflowState.MATCHMAKING if self.stage_manager.is_matchmaking_guard_active(now) else BotWorkflowState.IN_MATCH
                        elif self.state == "end":
                            workflow_state = BotWorkflowState.POST_MATCH
                    self.reporter.heartbeat(
                        workflow_state=str(workflow_state),
                        process_state=BotProcessState.ACTIVE,
                        selected_brawler=self._current_brawler(),
                        extras=extras,
                    )
                    self.last_report_at = now
            except (ConnectionError, OSError) as exc:
                recover_now = time.time()
                recovery_state = self._recover_scrcpy_transport(exc, recover_now)
                if recovery_state == "defer":
                    time.sleep(0.4)
                    continue
                if recovery_state != "recovered":
                    raise
                elapsed = time.time() - loop_started_at
                delay = self._loop_interval() - elapsed
                if delay > 0:
                    time.sleep(delay)
                continue

            elapsed = time.time() - loop_started_at
            delay = self._loop_interval() - elapsed
            if delay > 0:
                time.sleep(delay)


def fetch_brawlers() -> list[str]:
    brawlers = utils.get_brawler_list()
    try:
        utils.update_missing_brawlers_info(brawlers)
    except Exception as exc:
        print(f"Warning: failed to refresh missing brawler info: {exc}")
    return brawlers


def select_brawlers_via_gui(brawlers: list[str]) -> list[dict[str, Any]] | None:
    result: dict[str, list[dict[str, Any]] | None] = {"data": None}

    def set_data(value):
        result["data"] = value

    SelectBrawler(set_data, brawlers)
    return result["data"]


def load_latest_brawler_data() -> list[dict[str, Any]] | None:
    target_file = resolve_latest_brawler_data_path()
    if not target_file.exists():
        return None
    try:
        data = json.loads(target_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data or None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Only verify runtime imports and exit.")
    parser.add_argument(
        "--from-latest",
        action="store_true",
        help="Skip GUI and start from latest_brawler_data.json if present.",
    )
    parser.add_argument("--skip-gui", action="store_true", help="Start without interactive SelectBrawler UI.")
    parser.add_argument("--assigned-brawler", help="Assigned brawler for championship worker mode.")
    parser.add_argument("--assigned-pick-package-json", help="Assigned full pick package for championship worker mode.")
    parser.add_argument("--coordinator-url", help="Championship coordinator base URL.")
    parser.add_argument("--bot-id")
    parser.add_argument("--team-id")
    parser.add_argument("--instance-id")
    parser.add_argument("--instance-serial")
    parser.add_argument("--match-id")
    parser.add_argument("--match-context-version", type=int, default=0)
    parser.add_argument("--platform")
    parser.add_argument("--command-id")
    parser.add_argument("--friendly-host", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        print("balanced-runner-smoke-ok")
        return 0

    effective_instance_serial = args.instance_serial or os.environ.get("PYLA_INSTANCE_SERIAL", "").strip() or None

    if effective_instance_serial:
        os.environ["PYLA_INSTANCE_SERIAL"] = effective_instance_serial
        if ":" in effective_instance_serial:
            serial_port = effective_instance_serial.split(":", 1)[1]
            if serial_port.isdigit():
                os.environ["PYLA_EMULATOR_PORT"] = serial_port
    apply_runtime_overrides(effective_instance_serial)
    apply_push_runtime_state_overrides()
    install_scrcpy_deploy_patch(effective_instance_serial)
    validate_adb_transport(effective_instance_serial)
    if args.coordinator_url:
        apply_championship_data_overrides(args.bot_id)

    reporter = RuntimeReporter(
        args.coordinator_url,
        bot_id=args.bot_id,
        team_id=args.team_id,
        instance_id=args.instance_id or effective_instance_serial,
        match_id=args.match_id,
        match_context_version=args.match_context_version,
        command_id=args.command_id,
        platform=args.platform,
    )

    assigned_pick_package = parse_pick_package_json(args.assigned_pick_package_json)
    brawlers_data = None
    if assigned_pick_package and assigned_pick_package.get("brawler"):
        brawlers_data = build_championship_brawler_data(str(assigned_pick_package["brawler"]))
    elif args.assigned_brawler:
        brawlers_data = build_championship_brawler_data(args.assigned_brawler)
    elif args.from_latest:
        brawlers_data = load_latest_brawler_data()

    if brawlers_data is None:
        if args.skip_gui:
            brawlers_data = load_latest_brawler_data()
        else:
            brawlers = fetch_brawlers()
            brawlers_data = select_brawlers_via_gui(brawlers)

    if not brawlers_data:
        print("No brawler data selected. Exiting.")
        return 0

    utils.save_brawler_data(brawlers_data)
    print(f"Selected Brawler Data : {brawlers_data}")

    try:
        runner = BalancedBotRunner(
            brawlers_data,
            reporter=reporter if reporter.enabled else None,
            platform_name=args.platform,
            friendly_host=args.friendly_host,
        )
        if runner.championship_controller and assigned_pick_package:
            runner.championship_controller.current_pick_package = assigned_pick_package
            if assigned_pick_package.get("brawler"):
                runner.championship_controller.target_brawler = str(assigned_pick_package["brawler"])
        runner.run()
        return 0
    except Exception as exc:
        if reporter.enabled:
            reporter.runtime_error("RUNTIME_CRASH", str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
