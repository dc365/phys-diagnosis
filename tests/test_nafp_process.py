from __future__ import annotations

import os
import threading
import time

import numpy as np
import pytest

from backend.app.services import nafp_process


def _fake_layer() -> dict:
    return {
        "layer_id": "risk_hail_score",
        "title": "冰雹风险",
        "unit": "0-1",
        "values": np.asarray([[0.1, 0.2]]),
        "lat": np.asarray([30.0]),
        "lon": np.asarray([110.0, 111.0]),
        "min": 0.1,
        "max": 0.2,
        "data_code": "TEST",
        "root": "/tmp/nafp",
        "run_time": "2026-06-17T20:00:00",
        "forecast_hour": 24,
        "source_paths": [],
        "contour": {},
    }


def test_nafp_worker_runs_in_a_fresh_process_and_recovers_after_abnormal_exit():
    parent_pid = os.getpid()

    probe = nafp_process.probe_nafp_process()

    assert probe["worker_pid"] != parent_pid
    assert probe["parent_pid"] == parent_pid
    with pytest.raises(nafp_process.NafpWorkerError, match="exit code 139"):
        nafp_process.probe_nafp_process(crash=True)
    assert os.getpid() == parent_pid
    assert nafp_process.probe_nafp_process()["worker_pid"] != parent_pid


def test_nafp_layer_process_cache_coalesces_concurrent_cold_requests(monkeypatch):
    nafp_process.clear_nafp_layer_cache()
    started = threading.Event()
    release = threading.Event()
    calls = []
    results = []

    def fake_run(action, payload, *, timeout_seconds=None):
        calls.append((action, payload, timeout_seconds))
        started.set()
        assert release.wait(2)
        return _fake_layer()

    monkeypatch.setattr(nafp_process, "_run_isolated", fake_run)

    def invoke():
        results.append(
            nafp_process.load_nafp_layer_isolated(
                "risk_hail_score",
                data_code="TEST",
                root="/tmp/nafp",
                run_time="2026-06-17T20:00:00",
                forecast_hour=24,
            )
        )

    owner = threading.Thread(target=invoke)
    follower = threading.Thread(target=invoke)
    owner.start()
    assert started.wait(1)
    follower.start()
    time.sleep(0.05)
    assert len(calls) == 1

    release.set()
    owner.join(2)
    follower.join(2)

    assert len(calls) == 1
    assert len(results) == 2
    assert results[0]["values"].tolist() == results[1]["values"].tolist()


def test_nafp_area_risks_use_the_same_isolated_worker_boundary(monkeypatch):
    calls = []

    def fake_run(action, payload, *, timeout_seconds=None):
        calls.append((action, payload, timeout_seconds))
        return {"items": [], "failed": [], "summary": {}}

    monkeypatch.setattr(nafp_process, "_run_isolated", fake_run)

    result = nafp_process.evaluate_nafp_area_risks_isolated(
        root="/tmp/nafp",
        run_time="2026-06-17T20:00:00",
        forecast_hours=[24],
        towns=[],
        risk_types=["hail"],
    )

    assert result["failed"] == []
    assert calls[0][0] == "area_risks"
    assert calls[0][1]["forecast_hours"] == [24]
