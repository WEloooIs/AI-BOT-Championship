from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
RUNTIME_SCRIPT = BASE_DIR / "pyla_balanced_main.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    process = subprocess.Popen(
        [sys.executable, "-u", str(RUNTIME_SCRIPT), *args.runtime_args],
        cwd=BASE_DIR,
    )
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
