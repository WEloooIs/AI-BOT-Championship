from __future__ import annotations

import hashlib
import json
from typing import Any


def build_idempotency_key(command_type: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps({"command_type": command_type, "payload": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
