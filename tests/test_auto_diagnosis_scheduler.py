from datetime import datetime

from backend.app.api.v1 import auto_diagnostics as api
from weather_diag.diagnosis import auto_scheduler as scheduler


def test_auto_schedule_default_config_is_hourly(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "CONFIG_PATH", tmp_path / "auto_schedule.json")

    config = scheduler.load_auto_schedule_config()

    assert config["enabled"] is True
    assert config["mode"] == "interval"
    assert config["interval_minutes"] == 60
    assert config["fixed_times"] == []
    assert config["tasks"] == {"nafp_precompute": True, "sounding_preprocess": True}


def test_auto_schedule_fixed_time_tick_runs_once_per_minute(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "CONFIG_PATH", tmp_path / "auto_schedule.json")
    scheduler.save_auto_schedule_config({
        "enabled": True,
        "mode": "fixed",
        "interval_minutes": 60,
        "fixed_times": ["08:00"],
        "tasks": {"nafp_precompute": True, "sounding_preprocess": True},
    })
    monkeypatch.setattr(scheduler, "_SCHEDULER_STATE", {"last_interval_run": None, "fixed_run_keys": set()})
    calls = []
    monkeypatch.setattr(scheduler, "run_auto_diagnostics_once", lambda config=None: calls.append(config) or {"status": "scanned"})

    now = datetime(2026, 6, 29, 8, 0)

    assert scheduler.tick_auto_diagnosis_scheduler(now=now)["status"] == "scanned"
    assert scheduler.tick_auto_diagnosis_scheduler(now=now)["status"] == "skipped"
    assert len(calls) == 1


def test_auto_schedule_api_reads_and_updates_config(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "CONFIG_PATH", tmp_path / "auto_schedule.json")

    saved = api.update_auto_schedule(api.AutoScheduleRequest(
        enabled=True,
        mode="fixed",
        interval_minutes=30,
        fixed_times=["8:0", "20:00"],
        tasks={"nafp_precompute": True, "sounding_preprocess": False},
    ))
    loaded = api.get_auto_schedule()

    assert saved["data"]["config"]["fixed_times"] == ["08:00", "20:00"]
    assert loaded["data"]["config"]["mode"] == "fixed"
    assert loaded["data"]["config"]["interval_minutes"] == 30
    assert loaded["data"]["config"]["tasks"]["sounding_preprocess"] is False
