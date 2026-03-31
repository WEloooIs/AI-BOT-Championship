from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from championship.runtime.bot_runtime_client import BotRuntimeClient


BASE_DIR = Path(__file__).resolve().parents[2]
COORDINATOR_URL = "http://127.0.0.1:8765"
REQUIRED_COORDINATOR_VERSION = "2026-03-30-runtime-attach"


class CoordinatorApi:
    def __init__(self, base_url: str = COORDINATOR_URL) -> None:
        self.client = BotRuntimeClient(base_url, timeout=4.0)
        self.health_client = BotRuntimeClient(base_url, timeout=1.5)

    def _is_compatible_health(self, health: dict) -> bool:
        return bool(
            health.get("coordinator_alive")
            and health.get("coordinator_version") == REQUIRED_COORDINATOR_VERSION
        )

    def _kill_coordinator_listener(self) -> None:
        try:
            output = subprocess.check_output(
                ["netstat", "-ano", "-p", "tcp"],
                cwd=BASE_DIR,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
        except Exception:
            return
        pids: set[str] = set()
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            proto, local_addr, _foreign_addr, state, pid = parts[:5]
            if proto.upper() != "TCP":
                continue
            if state.upper() != "LISTENING":
                continue
            if not local_addr.endswith(":8765"):
                continue
            pids.add(pid)
        for pid in pids:
            try:
                subprocess.run(
                    ["taskkill", "/PID", pid, "/F"],
                    cwd=BASE_DIR,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except Exception:
                continue

    def _spawn_coordinator(self) -> None:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [sys.executable, "-m", "championship.coordinator"],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    def ensure_running(self) -> None:
        health = self.client.get("/health")
        if self._is_compatible_health(health):
            return
        if health.get("coordinator_alive"):
            self._kill_coordinator_listener()
            time.sleep(0.8)
        self._spawn_coordinator()
        for _ in range(40):
            time.sleep(0.2)
            health = self.client.get("/health")
            if self._is_compatible_health(health):
                return
        raise RuntimeError("Coordinator did not start in time.")

    def dashboard(self) -> dict:
        return self.client.get("/api/views/dashboard")

    def history(self) -> dict:
        return self.client.get("/api/views/history")

    def health(self) -> dict:
        return self.health_client.get("/health")

    def instances(self) -> dict:
        return self.client.get("/api/instances")

    def post(self, path: str, payload: dict) -> dict:
        return self.client.post(path, payload)
