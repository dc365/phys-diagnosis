from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICES_SCRIPT = ROOT / "scripts" / "services.sh"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, *, open_: bool, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.1)
            is_open = sock.connect_ex(("127.0.0.1", port)) == 0
        if is_open is open_:
            return True
        time.sleep(0.05)
    return False


def _fake_python(tmp_path: Path) -> Path:
    path = tmp_path / "fake-python"
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "if [[ ${1:-} == *api_supervisor.py ]]; then exec \"$REAL_PYTHON\" \"$@\"; fi\n"
        "if [[ ${1:-} == -m && ${2:-} == uvicorn ]]; then\n"
        "  sleep \"${FAKE_API_START_DELAY:-0}\"\n"
        "  exec \"$REAL_PYTHON\" -m http.server \"$WEATHER_DIAG_API_PORT\" --bind 127.0.0.1\n"
        "fi\n"
        "if [[ ${1:-} == -m && ${2:-} == weather_diag.mcp.area_risk_dsl_mcp ]]; then\n"
        "  exec \"$REAL_PYTHON\" -m http.server \"$AREA_RISK_DSL_MCP_PORT\" --bind 127.0.0.1\n"
        "fi\n"
        "exec \"$REAL_PYTHON\" \"$@\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _service_env(tmp_path: Path, api_port: int, mcp_port: int) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHON": str(_fake_python(tmp_path)),
        "REAL_PYTHON": sys.executable,
        "WEATHER_DIAG_RUNTIME_DIR": str(tmp_path / "runtime"),
        "WEATHER_DIAG_API_HOST": "127.0.0.1",
        "WEATHER_DIAG_API_PORT": str(api_port),
        "AREA_RISK_DSL_MCP_HOST": "127.0.0.1",
        "AREA_RISK_DSL_MCP_PORT": str(mcp_port),
        "WEATHER_DIAG_START_TIMEOUT_SECONDS": "5",
    }


def _run_services(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SERVICES_SCRIPT), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )


def _terminate_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def test_api_supervisor_restarts_failed_child_and_stops_cleanly(tmp_path):
    counter = tmp_path / "starts.txt"
    child_code = (
        "from pathlib import Path; import sys, time; "
        "p=Path(sys.argv[1]); "
        "n=int(p.read_text())+1 if p.exists() else 1; "
        "p.write_text(str(n)); "
        "sys.exit(17) if n == 1 else time.sleep(30)"
    )
    env = {
        **os.environ,
        "WEATHER_DIAG_API_RESTART_DELAY_SECONDS": "0.2",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "scripts/api_supervisor.py",
            "--",
            sys.executable,
            "-c",
            child_code,
            str(counter),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if counter.exists() and counter.read_text() == "2":
            break
        time.sleep(0.05)

    assert counter.read_text() == "2"
    process.terminate()
    assert process.wait(timeout=5) == 0
    output = process.stdout.read()
    assert "exited unexpectedly with code 17" in output
    assert "starting API child" in output


def test_services_script_starts_api_through_supervisor():
    script = Path("scripts/services.sh").read_text(encoding="utf-8")

    assert "scripts/api_supervisor.py" in script
    assert "PYTHONFAULTHANDLER" in script


def test_services_restart_recovers_when_supervisor_pidfile_was_lost(tmp_path):
    api_port = _free_port()
    mcp_port = _free_port()
    env = _service_env(tmp_path, api_port, mcp_port)
    pidfile = tmp_path / "runtime" / "pids" / "api.pid"
    original_pid = None
    try:
        started = _run_services(env, "start", "api")
        assert started.returncode == 0, started.stdout + started.stderr
        assert _wait_for_port(api_port, open_=True)
        original_pid = int(pidfile.read_text())
        pidfile.unlink()

        restarted = _run_services(env, "restart", "api")

        assert restarted.returncode == 0, restarted.stdout + restarted.stderr
        assert "unmanaged pid" not in restarted.stderr
        assert pidfile.exists()
        assert int(pidfile.read_text()) != original_pid
        assert _wait_for_port(api_port, open_=True)
    finally:
        _run_services(env, "stop", "api")
        if original_pid is not None:
            _terminate_pid(original_pid)


def test_api_start_timeout_does_not_leave_an_unmanaged_listener(tmp_path):
    api_port = _free_port()
    mcp_port = _free_port()
    env = _service_env(tmp_path, api_port, mcp_port)
    env["WEATHER_DIAG_START_TIMEOUT_SECONDS"] = "1"
    env["FAKE_API_START_DELAY"] = "2"

    result = _run_services(env, "start", "api")

    assert result.returncode != 0
    assert _wait_for_port(api_port, open_=False, timeout=4)
    assert not (tmp_path / "runtime" / "pids" / "api.pid").exists()


def test_start_all_still_attempts_mcp_when_api_port_is_occupied(tmp_path):
    api_port = _free_port()
    mcp_port = _free_port()
    env = _service_env(tmp_path, api_port, mcp_port)
    occupied = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(api_port), "--bind", "127.0.0.1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert _wait_for_port(api_port, open_=True)

        result = _run_services(env, "start", "all")

        assert result.returncode != 0
        assert "cannot start" in result.stderr
        assert _wait_for_port(mcp_port, open_=True)
    finally:
        _run_services(env, "stop", "area-risk-mcp")
        occupied.terminate()
        occupied.wait(timeout=5)


def test_systemd_units_restart_both_services_and_enable_boot_start():
    api_unit = Path("deploy/systemd/bdp-dm-physical-api.service").read_text(encoding="utf-8")
    mcp_unit = Path("deploy/systemd/bdp-dm-physical-mcp.service").read_text(encoding="utf-8")

    assert "--port 11011" in api_unit
    assert "AREA_RISK_DSL_MCP_PORT=11012" in mcp_unit
    for unit in (api_unit, mcp_unit):
        assert "Restart=on-failure" in unit
        assert "WantedBy=multi-user.target" in unit
        assert "KillMode=mixed" in unit


def test_services_script_supports_systemd_219_main_pid_output():
    script = Path("scripts/services.sh").read_text(encoding="utf-8")

    assert "sed -n 's/^MainPID=//p'" in script
    assert "systemctl show -p MainPID --value" not in script
