from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ArtifactExporter:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.reports_dir = base_dir / "reports"
        self.highlights_dir = base_dir / "highlights"
        self.tournaments_dir = base_dir / "tournaments"
        for path in (self.reports_dir, self.highlights_dir, self.tournaments_dir):
            path.mkdir(parents=True, exist_ok=True)

    def write_json(self, folder: Path, name: str, payload: dict[str, Any]) -> None:
        (folder / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
