from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    commands = [
        [
            sys.executable,
            "-m",
            "uvicorn",
            "smart_house_hunting.main:app",
            "--port",
            "7004",
            "--reload",
        ],
        ["npm", "--prefix", "frontend", "run", "dev"],
    ]
    processes = [subprocess.Popen(command, cwd=ROOT) for command in commands]

    def stop(_signum: int, _frame: object) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.25)
    finally:
        stop(signal.SIGTERM, None)
        for process in processes:
            process.wait()

    return next((process.returncode for process in processes if process.returncode), 0)


if __name__ == "__main__":
    raise SystemExit(main())
