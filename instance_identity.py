from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
ADB_EXE = BASE_DIR / "_internal" / "adbutils" / "binaries" / "adb.exe"
INSTANCE_ALIAS_FILE = BASE_DIR / "instance_aliases.json"
INSTANCE_RESOLUTION_LOG = BASE_DIR / "instance_resolution.log"
BLUESTACKS_CONF_PATHS = [
    Path(r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf"),
    Path(r"C:\ProgramData\BlueStacks\bluestacks.conf"),
]
MUMU_INSTALL_CONFIG_PATHS = [
    Path(r"C:\Users\q\AppData\Roaming\NetEase\MuMuPlayerGlobal\install_config.json"),
    Path(r"C:\Program Files\Netease\MuMuPlayer\configs\install_config.json"),
]

MUMU_BASE_DIR = Path(r"C:\Users\q\AppData\Roaming\NetEase\MuMuPlayerGlobal")
MUMU_LOG_GLOBS = ("logs/nx_main.log", "logs/nx_main.log.*")

DEFAULT_CANDIDATE_PORTS = [16384, 16416, 16432, 5555, 5565, 5635]
KNOWN_TEAM_TAGS = ("FUT", "ZL", "NX", "SK")
_INSTANCE_CACHE: dict[str, Any] = {"timestamp": 0.0, "current_port": None, "instances": []}


@dataclass(slots=True)
class ResolvedInstance:
    serial: str
    vendor: str
    instance_name: str | None
    window_title: str | None
    display_label: str
    model: str
    port: int
    pid: int | None
    is_exact_targetable: bool
    match_confidence: float
    source_details: dict[str, Any]
    alias: str | None = None
    emulator: str | None = None
    instance_id: str | None = None
    config_emulator_name: str = "Others"
    resolved_name_source: str = "fallback"
    debug_summary: str = ""
    parsed_team_tag: str | None = None
    parsed_player_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_team_tag_name(label: str | None) -> tuple[str | None, str | None]:
    if not label:
        return None, None
    parts = [part for part in re.split(r"\s+", str(label).strip()) if part]
    if len(parts) < 2:
        return None, None
    team_tag = parts[0].upper()
    if team_tag not in KNOWN_TEAM_TAGS:
        return None, None
    player_name = " ".join(parts[1:]).strip()
    if not player_name:
        return None, None
    return team_tag, player_name


def safe_run(args: list[str], timeout: int = 5) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args=args, returncode=124, stdout="", stderr=f"timeout after {timeout}s")


def ensure_adb_started() -> None:
    if ADB_EXE.exists():
        safe_run([str(ADB_EXE), "start-server"], timeout=5)


def load_instance_aliases() -> dict[str, dict[str, str]]:
    if not INSTANCE_ALIAS_FILE.exists():
        return {"serials": {}, "instance_keys": {}}
    try:
        data = json.loads(INSTANCE_ALIAS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"serials": {}, "instance_keys": {}}
    serials = data.get("serials") if isinstance(data, dict) else {}
    instance_keys = data.get("instance_keys") if isinstance(data, dict) else {}
    return {
        "serials": {str(key): str(value) for key, value in (serials or {}).items() if str(value).strip()},
        "instance_keys": {str(key): str(value) for key, value in (instance_keys or {}).items() if str(value).strip()},
    }


def save_instance_aliases(data: dict[str, dict[str, str]]) -> None:
    payload = {
        "serials": dict(sorted((data.get("serials") or {}).items())),
        "instance_keys": dict(sorted((data.get("instance_keys") or {}).items())),
    }
    INSTANCE_ALIAS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def set_instance_alias(serial: str, alias: str, instance_key: str | None = None) -> None:
    value = alias.strip()
    store = load_instance_aliases()
    if value:
        store.setdefault("serials", {})[serial] = value
        if instance_key:
            store.setdefault("instance_keys", {})[instance_key] = value
    save_instance_aliases(store)


def remove_instance_alias(serial: str, instance_key: str | None = None) -> None:
    store = load_instance_aliases()
    store.setdefault("serials", {}).pop(serial, None)
    if instance_key:
        store.setdefault("instance_keys", {}).pop(instance_key, None)
    save_instance_aliases(store)


def parse_model_from_line(line: str) -> str:
    match = re.search(r"model:([^\s]+)", line)
    if match:
        return match.group(1).replace("_", " ")
    return "Unknown"


def parse_field_from_line(line: str, field_name: str) -> str | None:
    match = re.search(rf"{re.escape(field_name)}:([^\s]+)", line)
    if match:
        return match.group(1).replace("_", " ")
    return None


def parse_bluestacks_metadata() -> tuple[dict[int, dict[str, Any]], list[str]]:
    ports: dict[int, dict[str, Any]] = {}
    debug_lines: list[str] = []
    adb_re = re.compile(r'^bst\.instance\.([^.]+)\.adb_port="(\d+)"$')
    status_adb_re = re.compile(r'^bst\.instance\.([^.]+)\.status\.adb_port="(\d+)"$')
    name_re = re.compile(r'^bst\.instance\.([^.]+)\.display_name="(.*)"$')
    for path in BLUESTACKS_CONF_PATHS:
        if not path.exists():
            debug_lines.append(f"bluestacks_conf_missing path={path}")
            continue
        names: dict[str, str] = {}
        adb_ports: dict[str, int] = {}
        runtime_ports: dict[str, int] = {}
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            adb_match = adb_re.match(line)
            if adb_match:
                adb_ports[adb_match.group(1)] = int(adb_match.group(2))
                continue
            status_match = status_adb_re.match(line)
            if status_match:
                runtime_ports[status_match.group(1)] = int(status_match.group(2))
                continue
            name_match = name_re.match(line)
            if name_match:
                names[name_match.group(1)] = name_match.group(2)
        instance_keys = set(adb_ports) | set(runtime_ports)
        for key in instance_keys:
            configured_port = adb_ports.get(key)
            runtime_port = runtime_ports.get(key)
            metadata = {
                "instance_key": f"bluestacks:{key}",
                "vendor": "BlueStacks",
                "internal_name": key,
                "display_name": names.get(key) or key,
                "adb_port": configured_port,
                "runtime_adb_port": runtime_port,
                "source": "bluestacks_conf",
                "conf_path": str(path),
            }
            for port_value, port_source in ((configured_port, "adb_port"), (runtime_port, "status.adb_port")):
                if not port_value:
                    continue
                port_metadata = dict(metadata)
                port_metadata["port_source"] = port_source
                ports[int(port_value)] = port_metadata
        debug_lines.append(f"bluestacks_conf_loaded path={path} configured={len(adb_ports)} runtime={len(runtime_ports)}")
        if instance_keys:
            break
    return ports, debug_lines


def load_bluestacks_windows() -> tuple[list[dict[str, Any]], list[str]]:
    command = (
        "Get-Process HD-Player -ErrorAction SilentlyContinue | "
        "Select-Object Id,MainWindowTitle | ConvertTo-Json -Compress"
    )
    result = safe_run(["powershell", "-NoProfile", "-Command", command], timeout=5)
    if result.returncode != 0 or not result.stdout.strip():
        return [], [f"bluestacks_window_probe_failed rc={result.returncode}"]
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], ["bluestacks_window_probe_invalid_json"]
    if isinstance(payload, dict):
        items = [payload]
    else:
        items = [item for item in payload if isinstance(item, dict)]
    windows: list[dict[str, Any]] = []
    for item in items:
        title = str(item.get("MainWindowTitle") or "").strip()
        pid = item.get("Id")
        if not title:
            continue
        windows.append({"pid": int(pid) if pid is not None else None, "title": title, "vendor": "BlueStacks"})
    return windows, [f"bluestacks_window_probe_loaded count={len(windows)}"]


def load_local_port_owners() -> tuple[dict[int, dict[str, Any]], list[str]]:
    command = (
        "$ports = Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -ErrorAction SilentlyContinue | "
        "Select-Object -Property LocalPort,OwningProcess -Unique; "
        "$rows = foreach ($port in $ports) { "
        "  $proc = Get-CimInstance Win32_Process -Filter (\"ProcessId = {0}\" -f $port.OwningProcess) -ErrorAction SilentlyContinue; "
        "  if ($proc) { "
        "    [pscustomobject]@{ "
        "      LocalPort = [int]$port.LocalPort; "
        "      OwningProcess = [int]$port.OwningProcess; "
        "      ProcessName = $proc.Name; "
        "      ParentProcessId = [int]$proc.ParentProcessId; "
        "      CommandLine = $proc.CommandLine "
        "    } "
        "  } "
        "}; "
        "$rows | ConvertTo-Json -Compress"
    )
    result = safe_run(["powershell", "-NoProfile", "-Command", command], timeout=8)
    if result.returncode != 0 or not result.stdout.strip():
        return {}, [f"local_port_probe_failed rc={result.returncode}"]
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}, ["local_port_probe_invalid_json"]
    if isinstance(payload, dict):
        items = [payload]
    else:
        items = [item for item in payload if isinstance(item, dict)]
    ports: dict[int, dict[str, Any]] = {}
    for item in items:
        local_port = item.get("LocalPort")
        if local_port is None:
            continue
        port = int(local_port)
        ports[port] = {
            "port": port,
            "pid": int(item.get("OwningProcess") or 0) or None,
            "process_name": str(item.get("ProcessName") or "").strip(),
            "parent_pid": int(item.get("ParentProcessId") or 0) or None,
            "command_line": str(item.get("CommandLine") or "").strip(),
        }
    return ports, [f"local_port_probe_loaded count={len(ports)}"]


def parse_mumu_install_metadata() -> tuple[dict[str, Any], list[str]]:
    debug_lines: list[str] = []
    metadata: dict[str, Any] = {}
    for path in MUMU_INSTALL_CONFIG_PATHS:
        if not path.exists():
            debug_lines.append(f"mumu_install_config_missing path={path}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            debug_lines.append(f"mumu_install_config_invalid path={path}")
            continue
        display_name = str(payload.get("display_name") or payload.get("name") or "MuMu").strip() or "MuMu"
        metadata = {"display_name": display_name, "path": str(path)}
        debug_lines.append(f"mumu_install_config_loaded path={path} display_name={display_name!r}")
        break
    return metadata, debug_lines


def parse_mumu_name_registry() -> tuple[dict[int, str], list[str]]:
    debug_lines: list[str] = []
    registry: dict[int, str] = {}
    log_paths: list[Path] = []
    for pattern in MUMU_LOG_GLOBS:
        log_paths.extend(sorted(MUMU_BASE_DIR.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True))
    seen_paths: set[Path] = set()
    index_re = re.compile(r"param=\(index,\s*(\d+)\)")
    name_re = re.compile(r"param=\(name,\s*([^\)]+)\)")
    rename_re = re.compile(r"param=\(emulator_rename,\s*([^\)]+)\)")
    for path in log_paths:
        if path in seen_paths or not path.exists() or not path.is_file():
            continue
        seen_paths.add(path)
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        pending_index: int | None = None
        pending_name: str | None = None
        for line in lines:
            index_match = index_re.search(line)
            if index_match:
                pending_index = int(index_match.group(1))
                continue
            name_match = name_re.search(line)
            if name_match and pending_index is not None:
                candidate = name_match.group(1).strip()
                if candidate:
                    pending_name = candidate
                continue
            rename_match = rename_re.search(line)
            if rename_match and pending_index is not None:
                candidate = rename_match.group(1).strip() or pending_name
                if candidate:
                    registry[pending_index] = candidate
                pending_index = None
                pending_name = None
        if registry:
            debug_lines.append(f"mumu_name_registry_loaded path={path} count={len(registry)}")
            break
    if not registry:
        debug_lines.append("mumu_name_registry_empty")
    return registry, debug_lines


def load_mumu_windows() -> tuple[list[dict[str, Any]], list[str]]:
    command = (
        "Get-Process MuMuNxDevice,MuMuNxMain -ErrorAction SilentlyContinue | "
        "Select-Object Id,ProcessName,MainWindowTitle | ConvertTo-Json -Compress"
    )
    result = safe_run(["powershell", "-NoProfile", "-Command", command], timeout=5)
    if result.returncode != 0 or not result.stdout.strip():
        return [], [f"mumu_window_probe_failed rc={result.returncode}"]
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], ["mumu_window_probe_invalid_json"]
    if isinstance(payload, dict):
        items = [payload]
    else:
        items = [item for item in payload if isinstance(item, dict)]
    windows: list[dict[str, Any]] = []
    for item in items:
        title = str(item.get("MainWindowTitle") or "").strip()
        if not title:
            continue
        process_name = str(item.get("ProcessName") or "").strip()
        windows.append(
            {
                "pid": int(item.get("Id")) if item.get("Id") is not None else None,
                "title": title,
                "process_name": process_name,
                "vendor": "MuMu",
            }
        )
    return windows, [f"mumu_window_probe_loaded count={len(windows)}"]


def is_emulator_port_owner(owner: dict[str, Any]) -> bool:
    source = f"{owner.get('process_name', '')} {owner.get('command_line', '')}".lower()
    return any(
        marker in source
        for marker in (
            "hd-player",
            "bluestacks",
            "mumu",
            "netease",
            "ldplayer",
            "dnplayer",
            "memu",
            "nemu",
        )
    )


def candidate_ports(current_port: int | None, metadata_ports: list[int], port_owners: dict[int, dict[str, Any]]) -> list[int]:
    ports: list[int] = []
    if current_port:
        ports.append(current_port)
    ports.extend(port for port in metadata_ports if port in port_owners)
    ports.extend(sorted(port for port, owner in port_owners.items() if is_emulator_port_owner(owner)))
    ports.extend(DEFAULT_CANDIDATE_PORTS)
    unique: list[int] = []
    seen: set[int] = set()
    for port in ports:
        if port and port not in seen:
            unique.append(port)
            seen.add(port)
    return unique


def parse_adb_device_states(adb_output: str) -> dict[str, str]:
    states: dict[str, str] = {}
    for raw_line in adb_output.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("List of devices attached"):
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        states[parts[0]] = parts[1]
    return states


def normalize_vendor(
    serial: str,
    raw_line: str,
    port: int,
    blue_metadata: dict[int, dict[str, Any]],
    port_owners: dict[int, dict[str, Any]],
) -> tuple[str, str]:
    source = f"{serial} {raw_line}".lower()
    owner = port_owners.get(port) if port else None
    owner_source = f"{owner.get('process_name', '')} {owner.get('command_line', '')}".lower() if owner else ""
    if port in blue_metadata:
        return "BlueStacks", "bluestacks_conf"
    if "mumu" in owner_source or "netease" in owner_source or "nemu" in owner_source:
        return "MuMu", "port_owner"
    if "hd-player" in owner_source or "bluestacks" in owner_source:
        return "BlueStacks", "port_owner"
    if "ldplayer" in owner_source or "dnplayer" in owner_source:
        return "LDPlayer", "port_owner"
    if "memu" in owner_source:
        return "MEmu", "port_owner"
    if "bluestacks" in source or "hd-player" in source:
        return "BlueStacks", "adb_line"
    if "mumu" in source or "netease" in source or "nemu" in source:
        return "MuMu", "adb_line"
    if "ldplayer" in source or "dnplayer" in source:
        return "LDPlayer", "adb_line"
    if "memu" in source:
        return "MEmu", "adb_line"
    if serial.startswith("emulator-"):
        return "Android Emulator", "serial_prefix"
    if serial.startswith("127.0.0.1:"):
        return "Local ADB Device", "serial_prefix"
    return "Unknown Device", "fallback"


def config_emulator_name_for_vendor(vendor: str) -> str:
    if vendor in {"BlueStacks", "LDPlayer", "MEmu"}:
        return vendor
    return "Others"


def resolve_instance_name(
    serial: str,
    vendor: str,
    port: int,
    aliases: dict[str, dict[str, str]],
    blue_metadata: dict[int, dict[str, Any]],
    blue_windows: list[dict[str, Any]],
    port_owners: dict[int, dict[str, Any]],
    mumu_metadata: dict[str, Any],
    mumu_windows: list[dict[str, Any]],
    mumu_name_registry: dict[int, str],
) -> tuple[str | None, str | None, int | None, str | None, float, dict[str, Any]]:
    debug: dict[str, Any] = {"serial": serial, "port": port, "vendor": vendor}
    instance_key: str | None = None
    instance_name: str | None = None
    window_title: str | None = None
    pid: int | None = None
    source = "fallback"
    confidence = 0.45

    metadata = blue_metadata.get(port) if vendor == "BlueStacks" and port else None
    if metadata:
        instance_key = str(metadata["instance_key"])
        instance_name = str(metadata["display_name"]).strip() or None
        source = "bluestacks_conf"
        confidence = 0.96 if instance_name else 0.88
        debug["metadata"] = metadata
        for window in blue_windows:
            if instance_name and window["title"].strip().lower() == instance_name.lower():
                window_title = window["title"]
                pid = int(window["pid"]) if window.get("pid") is not None else None
                source = "bluestacks_conf+window_title"
                confidence = 1.0
                debug["window_match"] = window
                break
    elif vendor == "BlueStacks":
        debug["window_candidates"] = blue_windows
        if len(blue_windows) == 1:
            window = blue_windows[0]
            window_title = window["title"]
            pid = int(window["pid"]) if window.get("pid") is not None else None
            instance_name = window_title
            source = "window_title"
            confidence = 0.68
            debug["window_match"] = window
        else:
            debug["fallback_reason"] = "unable_to_confidently_match_bluestacks_window"
    elif vendor == "MuMu":
        owner = port_owners.get(port) if port else None
        internal_name: str | None = None
        internal_index: int | None = None
        if owner:
            debug["port_owner"] = owner
            command_line = str(owner.get("command_line") or "")
            comment_match = re.search(r"--comment\s+([^\s]+)", command_line)
            if comment_match:
                internal_name = comment_match.group(1).strip()
                instance_key = f"mumu:{internal_name}"
                debug["internal_name"] = internal_name
                source = "mumu_process"
                confidence = 0.84
                index_match = re.search(r"-(\d+)$", internal_name)
                if index_match:
                    internal_index = int(index_match.group(1))
                    debug["internal_index"] = internal_index
        if internal_index is not None and internal_index in mumu_name_registry:
            instance_name = str(mumu_name_registry[internal_index]).strip() or None
            source = "mumu_log_registry"
            confidence = 0.95
            debug["mumu_registry_name"] = instance_name
        debug["window_candidates"] = mumu_windows
        usable_windows = [
            window
            for window in mumu_windows
            if window.get("title") and str(window["title"]).strip().lower() not in {"mumuplayer"}
        ]
        if instance_name:
            for window in usable_windows:
                title = str(window.get("title") or "").strip()
                if title and title.lower() == instance_name.lower():
                    window_title = title
                    pid = int(window["pid"]) if window.get("pid") is not None else None
                    debug["window_match"] = window
                    confidence = max(confidence, 0.98)
                    break
        elif len(usable_windows) == 1:
            window = usable_windows[0]
            window_title = str(window["title"]).strip()
            pid = int(window["pid"]) if window.get("pid") is not None else None
            instance_name = window_title or None
            source = "window_title"
            confidence = 0.9 if instance_key else 0.76
            debug["window_match"] = window
        elif len(usable_windows) > 1:
            debug["fallback_reason"] = "multiple_mumu_windows_no_exact_mapping"
        if not instance_name and mumu_metadata.get("display_name"):
            instance_name = str(mumu_metadata["display_name"]).strip() or None
            source = "mumu_install_config"
            confidence = max(confidence, 0.7)
            debug["mumu_metadata"] = mumu_metadata

    alias = aliases.get("serials", {}).get(serial)
    if not alias and instance_key:
        alias = aliases.get("instance_keys", {}).get(instance_key)
    if alias:
        instance_name = alias.strip()
        source = "alias"
        confidence = 1.0
        debug["alias"] = alias

    if not instance_name and vendor == "Android Emulator":
        instance_name = "Android Emulator"
        source = "vendor_fallback"
        confidence = 0.85
    elif not instance_name and vendor in {"LDPlayer", "MEmu"}:
        instance_name = vendor
        source = "vendor_fallback"
        confidence = 0.72
    elif not instance_name and vendor == "MuMu":
        instance_name = str(mumu_metadata.get("display_name") or "MuMu").strip() or "MuMu"
        source = "vendor_fallback"
        confidence = max(confidence, 0.7)
    elif not instance_name and vendor == "Local ADB Device":
        source = "vendor_fallback"
        confidence = 0.55
    elif not instance_name:
        source = "fallback"
        confidence = 0.4

    return instance_name, window_title, pid, instance_key, confidence, {"resolved_name_source": source, **debug}


def build_display_label(instance_name: str | None, vendor: str, serial: str) -> str:
    if instance_name and instance_name not in {vendor, serial}:
        return f"{instance_name} - {vendor} - {serial}"
    if vendor and vendor != "Unknown Device":
        return f"{vendor} - {serial}"
    return serial


def write_instance_resolution_log(instances: list[ResolvedInstance], raw_lines: list[str], debug_lines: list[str]) -> None:
    lines = [f"[{datetime.now().isoformat(timespec='seconds')}] instance resolution"]
    lines.append("adb_lines:")
    if raw_lines:
        lines.extend(f"  {line}" for line in raw_lines)
    else:
        lines.append("  <none>")
    lines.append("resolver_debug:")
    lines.extend(f"  {line}" for line in debug_lines)
    lines.append("resolved_instances:")
    if not instances:
        lines.append("  <none>")
    for item in instances:
        source = item.source_details.get("resolved_name_source", item.resolved_name_source)
        lines.append(
            "  "
            + f"serial={item.serial} vendor={item.vendor} display_label={item.display_label!r} "
            + f"model={item.model!r} port={item.port or 'n/a'} source={source} "
            + f"confidence={item.match_confidence:.2f} exact={item.is_exact_targetable} "
            + f"team_tag={item.parsed_team_tag or '-'} player={item.parsed_player_name or '-'}"
        )
        if item.source_details:
            lines.append("    " + json.dumps(item.source_details, ensure_ascii=False, sort_keys=True))
    INSTANCE_RESOLUTION_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_instances(current_port: int | None = None) -> list[dict[str, Any]]:
    aliases = load_instance_aliases()
    blue_metadata, debug_lines = parse_bluestacks_metadata()
    blue_windows, window_debug = load_bluestacks_windows()
    mumu_metadata, mumu_debug = parse_mumu_install_metadata()
    mumu_windows, mumu_window_debug = load_mumu_windows()
    mumu_name_registry, mumu_name_debug = parse_mumu_name_registry()
    port_owners, port_owner_debug = load_local_port_owners()
    debug_lines.extend(window_debug)
    debug_lines.extend(mumu_debug)
    debug_lines.extend(mumu_window_debug)
    debug_lines.extend(mumu_name_debug)
    debug_lines.extend(port_owner_debug)

    ensure_adb_started()
    result = safe_run([str(ADB_EXE), "devices", "-l"], timeout=5)
    device_states = parse_adb_device_states(result.stdout)
    for port in candidate_ports(current_port, list(blue_metadata.keys()), port_owners):
        serial = f"127.0.0.1:{port}"
        state = device_states.get(serial)
        if state == "device":
            debug_lines.append(f"adb_connect_skipped serial={serial} state=device")
            continue
        try:
            connect_result = safe_run([str(ADB_EXE), "connect", serial], timeout=1)
            output = " ".join(part.strip() for part in (connect_result.stdout, connect_result.stderr) if part.strip())
            debug_lines.append(
                f"adb_connect_attempt serial={serial} prev_state={state or 'missing'} rc={connect_result.returncode} output={output or '<empty>'}"
            )
        except Exception as exc:
            debug_lines.append(f"adb_connect_failed serial={serial} prev_state={state or 'missing'} error={exc}")
    result = safe_run([str(ADB_EXE), "devices", "-l"], timeout=5)

    items: list[ResolvedInstance] = []
    raw_lines: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("List of devices attached"):
            continue
        raw_lines.append(stripped)
        parts = stripped.split()
        if len(parts) < 2:
            debug_lines.append(f"adb_line_skipped malformed={stripped!r}")
            continue
        if parts[1] != "device":
            debug_lines.append(f"adb_line_skipped serial={parts[0]} state={parts[1]}")
            continue
        serial = parts[0]
        port = 0
        if serial.startswith("127.0.0.1:"):
            tail = serial.split(":", 1)[1]
            if tail.isdigit():
                port = int(tail)
        model = parse_model_from_line(stripped)
        vendor, vendor_source = normalize_vendor(serial, stripped, port, blue_metadata, port_owners)
        instance_name, window_title, pid, instance_key, confidence, source_details = resolve_instance_name(
            serial=serial,
            vendor=vendor,
            port=port,
            aliases=aliases,
            blue_metadata=blue_metadata,
            blue_windows=blue_windows,
            port_owners=port_owners,
            mumu_metadata=mumu_metadata,
            mumu_windows=mumu_windows,
            mumu_name_registry=mumu_name_registry,
        )
        source_details["vendor_source"] = vendor_source
        source_details["model"] = model
        source_details["adb_line"] = stripped
        source_details["window_title"] = window_title
        source_details["instance_key"] = instance_key
        source_details["port"] = port
        display_label = build_display_label(instance_name, vendor, serial)
        parse_source = aliases.get("serials", {}).get(serial) or instance_name or window_title or display_label
        team_tag, player_name = parse_team_tag_name(parse_source)
        source_details["parsed_team_tag"] = team_tag
        source_details["parsed_player_name"] = player_name
        instance = ResolvedInstance(
            serial=serial,
            vendor=vendor,
            instance_name=instance_name,
            window_title=window_title,
            display_label=display_label,
            model=model,
            port=port,
            pid=pid,
            is_exact_targetable=serial.startswith("127.0.0.1:") or serial.startswith("emulator-"),
            match_confidence=confidence,
            source_details=source_details,
            alias=aliases.get("serials", {}).get(serial) or (aliases.get("instance_keys", {}).get(instance_key) if instance_key else None),
            emulator=vendor,
            instance_id=instance_key or serial,
            config_emulator_name=config_emulator_name_for_vendor(vendor),
            resolved_name_source=str(source_details.get("resolved_name_source", "fallback")),
            debug_summary=f"{source_details.get('resolved_name_source', 'fallback')} @ {confidence:.2f}",
            parsed_team_tag=team_tag,
            parsed_player_name=player_name,
        )
        items.append(instance)

    items.sort(key=lambda item: ((item.port or 999999), item.display_label.lower(), item.serial))
    write_instance_resolution_log(items, raw_lines, debug_lines)
    resolved = [item.to_dict() for item in items]
    _INSTANCE_CACHE["timestamp"] = time.monotonic()
    _INSTANCE_CACHE["current_port"] = current_port
    _INSTANCE_CACHE["instances"] = resolved
    return resolved


def resolve_instances_cached(current_port: int | None = None, *, ttl_seconds: float = 6.0, force: bool = False) -> list[dict[str, Any]]:
    cached_instances = _INSTANCE_CACHE.get("instances") or []
    cached_port = _INSTANCE_CACHE.get("current_port")
    cached_timestamp = float(_INSTANCE_CACHE.get("timestamp") or 0.0)
    if not force and cached_instances and cached_port == current_port and (time.monotonic() - cached_timestamp) <= ttl_seconds:
        return [dict(item) for item in cached_instances]
    return resolve_instances(current_port=current_port)
