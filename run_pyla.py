from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
RUNNER_PATH = BASE_DIR / "original_runtime_patch.py"


def resolve_log_path() -> Path:
    raw = os.environ.get("PYLA_RUNTIME_LOG_PATH", "").strip()
    env_override = Path(raw) if raw else None
    return env_override or (BASE_DIR / "pyla_runtime.log")


def should_suppress_line(line: str, state: dict[str, int | bool]) -> bool:
    if state["skip_tk_lines"] > 0:
        state["skip_tk_lines"] -= 1
        return True

    if state["skip_pin_memory_continuation"]:
        state["skip_pin_memory_continuation"] = False
        if "warnings.warn(warn_msg)" in line:
            return True

    if "torch\\utils\\data\\dataloader.py:668: UserWarning:" in line and "pin_memory" in line:
        state["skip_pin_memory_continuation"] = True
        return True

    if "Exception ignored in: <function Variable.__del__" in line:
        state["skip_tk_lines"] = 3
        return True

    return False


def main() -> int:
    log_path = resolve_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    suppress_state: dict[str, int | bool] = {
        "skip_pin_memory_continuation": False,
        "skip_tk_lines": 0,
    }

    command = [sys.executable, "-u", str(RUNNER_PATH), *sys.argv[1:]]
    instance_serial = os.environ.get("PYLA_INSTANCE_SERIAL", "").strip()
    latest_data_path = os.environ.get("PYLA_LATEST_BRAWLER_DATA_PATH", "").strip()
    auto_start_from_latest = os.environ.get("PYLA_START_FROM_LATEST", "").strip() == "1"
    if instance_serial:
        command.extend(["--instance-serial", instance_serial])
    if auto_start_from_latest and latest_data_path and Path(latest_data_path).exists():
        command.extend(["--from-latest", "--skip-gui"])

    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert process.stdout is not None
        for line in process.stdout:
            log_file.write(line)
            log_file.flush()

            if should_suppress_line(line, suppress_state):
                continue

            sys.stdout.write(line)
            sys.stdout.flush()

        return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
