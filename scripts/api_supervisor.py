#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time


def _log(message: str) -> None:
    print(
        f"{time.strftime('%Y-%m-%d %H:%M:%S')} [api-supervisor] {message}",
        flush=True,
    )


def supervise(command: list[str], *, label: str = "API") -> int:
    if not command:
        raise ValueError("missing child command")
    stopping = threading.Event()
    child: subprocess.Popen | None = None
    stop_lock = threading.Lock()

    def stop(_signum, _frame) -> None:
        if stopping.is_set():
            return
        stopping.set()

        def terminate_child() -> None:
            with stop_lock:
                current = child
                if current is None or current.poll() is not None:
                    return
                current.terminate()
                try:
                    current.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    _log("API child did not stop in 8s; killing it")
                    current.kill()

        threading.Thread(target=terminate_child, name="api-stop", daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    restart_delay = max(
        0.2,
        float(os.getenv("WEATHER_DIAG_API_RESTART_DELAY_SECONDS", "2")),
    )

    while not stopping.is_set():
        _log(f"starting {label} child: {' '.join(command)}")
        child = subprocess.Popen(command)
        exit_code = child.wait()
        if stopping.is_set():
            _log(f"{label} child stopped with exit code {exit_code}")
            return 0
        _log(
            f"{label} child exited unexpectedly with code {exit_code}; "
            f"restarting in {restart_delay:.1f}s"
        )
        stopping.wait(restart_delay)
    return 0


def main() -> int:
    args = sys.argv[1:]
    label = "API"
    if args[:1] == ["--label"]:
        if len(args) < 2:
            raise ValueError("--label requires a value")
        label = args[1]
        args = args[2:]
    if args[:1] == ["--"]:
        args = args[1:]
    return supervise(args, label=label)


if __name__ == "__main__":
    raise SystemExit(main())
