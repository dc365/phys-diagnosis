from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "services.sh"
README = ROOT / "README.md"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_services_script_exposes_service_lifecycle_commands():
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK)

    result = run_script("--help")

    assert result.returncode == 0
    assert "start|stop|restart|status|logs" in result.stdout
    assert "api" in result.stdout
    assert "area-risk-mcp" in result.stdout
    assert "AREA_RISK_DSL_MCP_TRANSPORT=http" in result.stdout


def test_services_status_is_safe_without_running_processes():
    result = run_script("status")

    assert result.returncode == 0
    assert "api" in result.stdout
    assert "area-risk-mcp" in result.stdout


def test_readme_documents_unified_background_service_script():
    readme = README.read_text(encoding="utf-8")

    assert "scripts/services.sh start" in readme
    assert "scripts/services.sh restart" in readme
    assert "scripts/services.sh stop" in readme
    assert "area-risk-mcp" in readme
    assert "http://localhost:11011/mcp" in readme
