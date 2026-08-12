from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from weather_diag.diagnosis import area_risk as area_risk_mod
from weather_diag.diagnosis.area_risk import area_risk_metadata
from weather_diag.mcp import area_risk_dsl as dsl_mod
from weather_diag.mcp import area_risk_dsl_mcp
from weather_diag.mcp.area_risk_dsl import (
    build_town_risk_dsl_response,
    resolve_forecast_hours_for_window,
    resolve_forecast_contexts,
    resolve_model_source,
    resolve_region_scope,
    town_s5_code,
)


def test_resolve_region_scope_accepts_fuzhou_alias_and_keeps_town_s5_code():
    scope = resolve_region_scope("fuzhou")

    assert scope["region_code"] == "350100"
    assert scope["region_level"] == "city"
    assert scope["region_name"] == "福州市"
    assert scope["town_count"] > 20
    assert {town.code for town in scope["towns"]} >= {"350102003", "350102004"}

    wenquan = next(town for town in scope["towns"] if town.code == "350102003")
    assert town_s5_code(wenquan) == "10203"


def test_resolve_forecast_hours_for_window_maps_valid_times_to_leads():
    hours = resolve_forecast_hours_for_window(
        run_time=datetime(2026, 6, 17, 20),
        forecast_hours=[0, 3, 6, 24, 27, 30],
        start_time=datetime(2026, 6, 18, 20),
        end_time=datetime(2026, 6, 18, 23),
    )

    assert hours == [24, 27]


def test_resolve_model_source_accepts_configured_model_labels():
    ecthin = resolve_model_source("ECTHIN")
    cma_gfs = resolve_model_source("CMA-GFS")

    assert ecthin["data_code"] == "NAFP_ECTHIN_NC"
    assert Path(ecthin["root"]).name == "NAFP_ECTHIN_NC"
    assert cma_gfs["data_code"] == "NAFP_CMA_GFS_NC"
    assert Path(cma_gfs["root"]).name == "NAFP_CMA_GFS_NC"


def test_build_town_risk_dsl_response_contains_risks_evidence_and_self_guide():
    area_risk_result = {
        "items": [
            {
                "area": {
                    "town_code": "350102003",
                    "town_name": "温泉街道",
                    "county_code": "350102",
                    "county_name": "鼓楼区",
                    "city_code": "350100",
                    "city_name": "福州市",
                },
                "forecast_hour": 24,
                "valid_time": "2026-06-18T20:00:00",
                "risks": [
                    {
                        "hazard_type": "persistent_heavy_rain",
                        "source_grid": "risk_persistent_heavy_rain_score",
                        "metadata": {"score_range": [0, 1], "score_unit": "risk_score"},
                        "score": 0.62345,
                        "evidence_chain": {
                            "dominant_factors": [
                                {
                                    "factor": "moisture_transport",
                                    "field": "moisture_transport",
                                    "label": "低层水汽输送",
                                    "mean_score": 0.554,
                                },
                                {
                                    "factor": "ascent",
                                    "field": "ascent",
                                    "label": "700hPa 上升运动",
                                    "mean_score": 0.482,
                                },
                            ],
                            "source_paths": ["/private/data/q/850/26061720.024"],
                        },
                    },
                    {
                        "hazard_type": "short_duration_heavy_rain",
                        "source_grid": "risk_short_duration_heavy_rain_score",
                        "score": 0.712,
                        "evidence_chain": {
                            "dominant_factors": [
                                {
                                    "factor": "cape",
                                    "field": "cape",
                                    "label": "CAPE",
                                    "mean_score": 0.666,
                                }
                            ]
                        },
                    },
                ],
            }
        ],
        "failed": [],
        "summary": {"town_count": 1, "risk_type_count": 6, "item_count": 1, "risk_count": 2},
    }

    response = build_town_risk_dsl_response(
        request={"region": "fuzhou", "models": ["EC"]},
        region_scope={
            "region_code": "350100",
            "region_level": "city",
            "region_name": "福州市",
            "town_count": 1,
        },
        model="EC",
        data_code="NAFP_ECTHIN_NC",
        run_time=datetime(2026, 6, 17, 20),
        forecast_hours=[24],
        start_time=datetime(2026, 6, 18, 20),
        end_time=datetime(2026, 6, 18, 23),
        area_risk_result=area_risk_result,
        risk_metadata=area_risk_metadata(),
        physical_evidence={
            "fields": {
                "CAPE": {
                    "dsl_field": "CAPE",
                    "api": "cape",
                    "label": "CAPE",
                    "unit": "J/kg",
                    "direction": "gte",
                    "watch": 1000,
                    "high": 2000,
                },
                "CIN": {
                    "dsl_field": "CIN",
                    "api": "cin",
                    "label": "CIN",
                    "unit": "J/kg",
                    "direction": "lte",
                    "watch": 150,
                    "high": 50,
                },
            },
            "values": {
                (24, "350102003"): {
                    "CAPE": 1600.25,
                    "CIN": -42.5,
                }
            },
        },
    )

    dsl = response["dsl"]
    assert "@B:FCST_TWN_PHY;" in dsl
    assert "@M:EC;" in dsl
    assert "@T:2606172000;" in dsl
    assert "@DT:1440;" in dsl
    assert "@ORD:DT>S5=R_PHR|R_SHR|R_TG|R_HAIL|R_ROT|R_SC|CAPE|CIN;" in dsl
    assert "R_PHR=risk_persistent_heavy_rain_score|risk_score_0_1|gte|0.6|0.75;" in dsl
    assert "CAPE=cape|J/kg|gte|1000|2000;" in dsl
    assert "CIN=cin|J/kg|lte|150|50;" in dsl
    assert "1440>10203=0.62|0.71|NA|NA|NA|NA|1600.25|-42.50;" in dsl

    assert response["risk_metadata"]["persistent_heavy_rain"]["dsl_field"] == "R_PHR"
    assert response["evidence_fields"]["CAPE"]["label"] == "CAPE"
    assert response["evidence_fields"]["CAPE"]["unit"] == "J/kg"
    assert response["area_risk"]["items"][0]["risks"][0]["score"] == 0.623
    assert response["area_risk"]["items"][0]["risks"][0]["metadata"]["score_range"] == [0, 1]
    assert "source_paths" not in response["area_risk"]["items"][0]["risks"][0]["evidence_chain"]
    assert "FCST_TWN_PHY" in response["dsl_structure_guide"]
    assert "风险值字段使用 0-1" in response["dsl_structure_guide"]


def test_get_town_risk_dsl_payload_omits_verbose_model_results(monkeypatch):
    monkeypatch.setattr(
        dsl_mod,
        "resolve_region_scope",
        lambda region: {
            "region_code": "350100",
            "region_level": "city",
            "region_name": "福州市",
            "town_count": 0,
            "towns": [],
        },
    )
    monkeypatch.setattr(
        dsl_mod,
        "resolve_model_source",
        lambda model, data_code=None: {
            "model": "EC",
            "data_code": "NAFP_ECTHIN_NC",
            "root": Path("/tmp/nafp"),
            "forecast_hours": [24],
        },
    )
    monkeypatch.setattr(
        dsl_mod,
        "resolve_forecast_context",
        lambda **_kwargs: {"run_time": datetime(2026, 6, 17, 20), "forecast_hours": [24]},
    )
    monkeypatch.setattr(
        dsl_mod,
        "evaluate_area_risks",
        lambda **_kwargs: {
            "items": [],
            "failed": [],
            "summary": {"town_count": 0, "risk_type_count": 6, "item_count": 0, "risk_count": 0},
        },
    )
    monkeypatch.setattr(dsl_mod, "build_physical_evidence", lambda **_kwargs: {"fields": {}, "values": {}})

    payload = dsl_mod.get_town_risk_dsl_payload(
        region="fuzhou",
        start_time=datetime(2026, 6, 18, 20),
        end_time=datetime(2026, 6, 18, 23),
        models="EC",
    )

    assert "model_results" not in payload
    assert "evidence_fields" not in payload
    assert payload["dsl"].startswith("@B:FCST_TWN_PHY;")
    assert payload["model_metadata"] == [
        {
            "model": "EC",
            "data_code": "NAFP_ECTHIN_NC",
            "run_time": "2026-06-17T20:00:00",
            "forecast_hours": [24],
        }
    ]
    assert payload["risk_metadata"]["persistent_heavy_rain"]["dsl_field"] == "R_PHR"
    assert "FCST_TWN_PHY" in payload["dsl_structure_guide"]


def test_get_town_risk_dsl_payload_legacy_path_shares_product_cache(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        dsl_mod,
        "resolve_region_scope",
        lambda region: {
            "region_code": "350100",
            "region_level": "city",
            "region_name": "福州市",
            "town_count": 0,
            "towns": [],
        },
    )
    monkeypatch.setattr(
        dsl_mod,
        "resolve_model_source",
        lambda model, data_code=None: {
            "model": "EC",
            "data_code": "NAFP_ECTHIN_NC",
            "root": Path("/tmp/nafp"),
            "forecast_hours": [24],
        },
    )
    monkeypatch.setattr(
        dsl_mod,
        "resolve_forecast_context",
        lambda **_kwargs: {"run_time": datetime(2026, 6, 17, 20), "forecast_hours": [24]},
    )

    def fake_evaluate_area_risks(**kwargs):
        captured["risk_input_cache"] = kwargs.get("risk_input_cache")
        captured["score_details_cache"] = kwargs.get("score_details_cache")
        return {
            "items": [],
            "failed": [],
            "summary": {"town_count": 0, "risk_type_count": 6, "item_count": 0, "risk_count": 0},
        }

    def fake_build_physical_evidence(**kwargs):
        captured["physical_risk_input_cache"] = kwargs.get("risk_input_cache")
        return {"fields": {}, "values": {}}

    monkeypatch.setattr(dsl_mod, "evaluate_area_risks", fake_evaluate_area_risks)
    monkeypatch.setattr(dsl_mod, "build_physical_evidence", fake_build_physical_evidence)

    dsl_mod.get_town_risk_dsl_payload(
        region="fuzhou",
        start_time=datetime(2026, 6, 18, 20),
        end_time=datetime(2026, 6, 18, 23),
        models="EC",
    )

    assert isinstance(captured["risk_input_cache"], dict)
    assert isinstance(captured["score_details_cache"], dict)
    assert captured["physical_risk_input_cache"] is captured["risk_input_cache"]


def test_get_town_risk_dsl_mcp_accepts_structured_windows(monkeypatch):
    captured = {}

    def fake_payload(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(area_risk_dsl_mcp, "get_town_risk_dsl_payload", fake_payload)

    windows = [{"label": "today", "start_time": "2026-07-04T00:00:00", "end_time": "2026-07-04T23:59:59"}]
    response = area_risk_dsl_mcp.get_town_risk_dsl(region="xiamen", windows=windows, run_time="   ")

    assert response == {"code": 0, "msg": "success", "data": {"ok": True}}
    assert captured["region"] == "xiamen"
    assert captured["windows"] == windows
    assert captured["run_time"] is None


def test_resolve_forecast_contexts_supports_three_time_matching_policies(monkeypatch):
    monkeypatch.setattr(
        dsl_mod,
        "discover_nafp_run_inventory",
        lambda **_kwargs: {
            "run_times": [
                {"run_time": "2026-07-04T20:00:00", "forecast_hours": [0, 3, 6]},
                {"run_time": "2026-07-04T08:00:00", "forecast_hours": [0, 3, 6, 9, 12]},
                {"run_time": "2026-07-03T20:00:00", "forecast_hours": [12, 15, 18, 21, 24]},
            ]
        },
    )
    monkeypatch.setattr(dsl_mod, "_configured_forecast_hours", lambda _data_code: [0, 3, 6, 9, 12, 15])

    start = datetime(2026, 7, 4, 10)
    end = datetime(2026, 7, 4, 23)

    single = resolve_forecast_contexts(
        data_code="NAFP_ECTHIN_NC",
        root=Path("/tmp/nafp"),
        run_time=None,
        start_time=start,
        end_time=end,
        policy="single_latest_run",
    )
    assert single == [
        {
            "run_time": datetime(2026, 7, 4, 20),
            "forecast_hours": [0, 3],
            "valid_times": ["2026-07-04T20:00:00", "2026-07-04T23:00:00"],
        }
    ]

    fixed = resolve_forecast_contexts(
        data_code="NAFP_ECTHIN_NC",
        root=Path("/tmp/nafp"),
        run_time=datetime(2026, 7, 4, 8),
        start_time=start,
        end_time=end,
        policy="fixed_run",
    )
    assert fixed == [
        {
            "run_time": datetime(2026, 7, 4, 8),
            "forecast_hours": [3, 6, 9, 12, 15],
            "valid_times": [
                "2026-07-04T11:00:00",
                "2026-07-04T14:00:00",
                "2026-07-04T17:00:00",
                "2026-07-04T20:00:00",
                "2026-07-04T23:00:00",
            ],
        }
    ]

    stitched = resolve_forecast_contexts(
        data_code="NAFP_ECTHIN_NC",
        root=Path("/tmp/nafp"),
        run_time=None,
        start_time=start,
        end_time=end,
        policy="latest_per_valid_time",
    )
    assert stitched == [
        {
            "run_time": datetime(2026, 7, 4, 8),
            "forecast_hours": [3, 6, 9],
            "valid_times": [
                "2026-07-04T11:00:00",
                "2026-07-04T14:00:00",
                "2026-07-04T17:00:00",
            ],
        },
        {
            "run_time": datetime(2026, 7, 4, 20),
            "forecast_hours": [0, 3],
            "valid_times": ["2026-07-04T20:00:00", "2026-07-04T23:00:00"],
        },
    ]


def test_get_town_risk_dsl_payload_builds_multi_window_dsl_and_risk_summary(monkeypatch):
    calls: list[tuple[str, int]] = []

    def fake_area_result(*, root, run_time, forecast_hours, towns, **_kwargs):
        run = dsl_mod.parse_run_time(run_time)
        items = []
        for hour in forecast_hours:
            calls.append((run.isoformat(), int(hour)))
            score = {
                (datetime(2026, 7, 4, 8), 3): 0.61,
                (datetime(2026, 7, 4, 8), 6): 0.64,
                (datetime(2026, 7, 4, 8), 9): 0.58,
                (datetime(2026, 7, 4, 20), 0): 0.82,
                (datetime(2026, 7, 4, 20), 3): 0.76,
            }.get((run, int(hour)), 0.2)
            items.append(
                {
                    "area": {
                        "town_code": "350203001",
                        "town_name": "town-a",
                        "county_code": "350203",
                        "county_name": "county-a",
                        "city_code": "350200",
                        "city_name": "city-a",
                        "s5": "20301",
                    },
                    "forecast_hour": int(hour),
                    "valid_time": (run + dsl_mod.timedelta(hours=int(hour))).isoformat(),
                    "risks": [
                        {"hazard_type": "severe_convection_composite", "score": score},
                        {"hazard_type": "short_duration_heavy_rain", "score": score - 0.1},
                    ],
                }
            )
        return {
            "items": items,
            "failed": [],
            "summary": {"town_count": 1, "risk_type_count": 6, "item_count": len(items), "risk_count": len(items) * 2},
        }

    monkeypatch.setattr(
        dsl_mod,
        "resolve_region_scope",
        lambda region: {
            "region_code": "350200",
            "region_level": "city",
            "region_name": "city-a",
            "town_count": 0,
            "towns": [],
        },
    )
    monkeypatch.setattr(
        dsl_mod,
        "resolve_model_source",
        lambda model, data_code=None: {
            "model": "EC",
            "data_code": "NAFP_ECTHIN_NC",
            "root": Path("/tmp/nafp"),
            "forecast_hours": [0, 3, 6, 9, 12],
        },
    )
    monkeypatch.setattr(
        dsl_mod,
        "discover_nafp_run_inventory",
        lambda **_kwargs: {
            "run_times": [
                {"run_time": "2026-07-04T20:00:00", "forecast_hours": [0, 3]},
                {"run_time": "2026-07-04T08:00:00", "forecast_hours": [3, 6, 9]},
            ]
        },
    )
    monkeypatch.setattr(dsl_mod, "evaluate_area_risks", fake_area_result)
    monkeypatch.setattr(dsl_mod, "build_physical_evidence", lambda **_kwargs: {"fields": {}, "values": {}})

    payload = dsl_mod.get_town_risk_dsl_payload(
        region="xiamen",
        models="EC",
        windows=[
            {
                "label": "today",
                "start_time": "2026-07-04T10:00:00",
                "end_time": "2026-07-04T23:00:00",
            }
        ],
        time_match_policy="latest_per_valid_time",
    )

    assert payload["mode"] == "multi_window_evidence"
    assert payload["request"]["time_match_policy"] == "latest_per_valid_time"
    assert len(payload["windows"]) == 1

    window = payload["windows"][0]
    assert window["label"] == "today"
    assert window["model_metadata"] == [
        {
            "model": "EC",
            "data_code": "NAFP_ECTHIN_NC",
            "run_time": "2026-07-04T08:00:00",
            "forecast_hours": [3, 6, 9],
            "valid_times": [
                "2026-07-04T11:00:00",
                "2026-07-04T14:00:00",
                "2026-07-04T17:00:00",
            ],
        },
        {
            "model": "EC",
            "data_code": "NAFP_ECTHIN_NC",
            "run_time": "2026-07-04T20:00:00",
            "forecast_hours": [0, 3],
            "valid_times": ["2026-07-04T20:00:00", "2026-07-04T23:00:00"],
        },
    ]

    dsl = window["dsl"]
    assert dsl.count("@B:FCST_TWN_PHY;") == 1
    assert "@WIN:today|2026-07-04T10:00:00|2026-07-04T23:00:00;" in dsl
    assert "@T:2607040800;" in dsl
    assert "@DT:180,360,540;" in dsl
    assert "@T:2607042000;" in dsl
    assert "@DT:0,180;" in dsl
    assert "#SUMMARY_RISK:" in dsl
    assert "R_SC=0.82|2607042000|20301|1|1|1|4;" in dsl
    assert "#SUMMARY_TOWN_RISK:" in dsl
    assert "20301>R_SC=0.82|2607042000|high|4|2;" in dsl
    assert window["failures"] == []
    assert calls == [
        ("2026-07-04T08:00:00", 3),
        ("2026-07-04T08:00:00", 6),
        ("2026-07-04T08:00:00", 9),
        ("2026-07-04T20:00:00", 0),
        ("2026-07-04T20:00:00", 3),
    ]


def test_get_town_risk_dsl_payload_fixed_run_requires_run_time():
    try:
        dsl_mod.get_town_risk_dsl_payload(
            region="xiamen",
            models="EC",
            windows=[
                {
                    "label": "today",
                    "start_time": "2026-07-04T20:00:00",
                    "end_time": "2026-07-04T23:00:00",
                }
            ],
            time_match_policy="fixed_run",
        )
    except ValueError as exc:
        assert "run_time is required when time_match_policy=fixed_run" in str(exc)
    else:
        raise AssertionError("fixed_run without run_time should fail before window evaluation")


def test_build_town_risk_window_dsl_response_adds_physical_summary_for_gte_and_lte():
    items = []
    for hour, valid_time in [(3, datetime(2026, 7, 4, 11)), (6, datetime(2026, 7, 4, 14))]:
        for town_code, s5 in [("350203001", "20301"), ("350203002", "20302")]:
            items.append(
                {
                    "area": {
                        "town_code": town_code,
                        "town_name": f"town-{s5}",
                        "county_code": "350203",
                        "county_name": "county-a",
                        "city_code": "350200",
                        "city_name": "city-a",
                        "s5": s5,
                    },
                    "forecast_hour": hour,
                    "valid_time": valid_time.isoformat(),
                    "risks": [],
                }
            )

    response = dsl_mod.build_town_risk_window_dsl_response(
        region_scope={
            "region_code": "350200",
            "region_level": "city",
            "region_name": "city-a",
            "town_count": 2,
            "towns": [],
        },
        model="EC",
        data_code="NAFP_ECTHIN_NC",
        window={
            "label": "today",
            "start_time": datetime(2026, 7, 4, 10),
            "end_time": datetime(2026, 7, 4, 15),
        },
        run_entries=[
            {
                "context": {
                    "run_time": datetime(2026, 7, 4, 8),
                    "forecast_hours": [3, 6],
                    "valid_times": ["2026-07-04T11:00:00", "2026-07-04T14:00:00"],
                },
                "area_risk_result": {
                    "items": items,
                    "failed": [],
                    "summary": {"town_count": 2, "risk_type_count": 6, "item_count": len(items), "risk_count": 0},
                },
                "physical_evidence": {
                    "fields": {
                        "CAPE": {
                            "dsl_field": "CAPE",
                            "api": "cape",
                            "label": "CAPE",
                            "unit": "J/kg",
                            "direction": "gte",
                            "watch": 1000,
                            "high": 2000,
                        },
                        "CIN": {
                            "dsl_field": "CIN",
                            "api": "cin",
                            "label": "CIN",
                            "unit": "J/kg",
                            "direction": "lte",
                            "watch": 150,
                            "high": 50,
                        },
                    },
                    "values": {
                        (3, "350203001"): {"CAPE": 1200, "CIN": 80},
                        (3, "350203002"): {"CAPE": 2300, "CIN": 55},
                        (6, "350203001"): {"CAPE": 2600, "CIN": 40},
                        (6, "350203002"): {"CAPE": 800, "CIN": 180},
                    },
                },
            }
        ],
        risk_metadata={},
    )

    dsl = response["dsl"]
    assert "#SUMMARY_PHY:" in dsl
    assert "CAPE=2600.00|2607041400|20301|high|1|2|2|2;" in dsl
    assert "CIN=40.00|2607041400|20301|high|1|2|2|2;" in dsl
    assert "#SUMMARY_TOWN_PHY:" in dsl
    assert "20301>CAPE=2600.00|2607041400|high|2|1;" in dsl
    assert "20301>CIN=40.00|2607041400|high|2|1;" in dsl
    assert "20302>CAPE=2300.00|2607041100|high|1|1;" in dsl
    assert "20302>CIN=55.00|2607041100|watch|1|0;" in dsl


def test_get_town_risk_dsl_payload_returns_all_requested_windows(monkeypatch):
    monkeypatch.setattr(
        dsl_mod,
        "resolve_region_scope",
        lambda region: {
            "region_code": "350200",
            "region_level": "city",
            "region_name": "city-a",
            "town_count": 0,
            "towns": [],
        },
    )
    monkeypatch.setattr(
        dsl_mod,
        "resolve_model_source",
        lambda model, data_code=None: {
            "model": "EC",
            "data_code": "NAFP_ECTHIN_NC",
            "root": Path("/tmp/nafp"),
            "forecast_hours": [3],
        },
    )
    monkeypatch.setattr(
        dsl_mod,
        "resolve_forecast_contexts",
        lambda **kwargs: [
            {
                "run_time": datetime(2026, 7, 4, 8),
                "forecast_hours": [3],
                "valid_times": [(datetime(2026, 7, 4, 8) + dsl_mod.timedelta(hours=3)).isoformat()],
            }
        ],
    )
    monkeypatch.setattr(
        dsl_mod,
        "evaluate_area_risks",
        lambda **_kwargs: {
            "items": [],
            "failed": [],
            "summary": {"town_count": 0, "risk_type_count": 6, "item_count": 0, "risk_count": 0},
        },
    )
    monkeypatch.setattr(dsl_mod, "build_physical_evidence", lambda **_kwargs: {"fields": {}, "values": {}})

    payload = dsl_mod.get_town_risk_dsl_payload(
        region="xiamen",
        models="EC",
        windows=[
            {"label": "yesterday", "start_time": "2026-07-03T00:00:00", "end_time": "2026-07-03T23:59:59"},
            {"label": "today", "start_time": "2026-07-04T00:00:00", "end_time": "2026-07-04T23:59:59"},
        ],
        time_match_policy="single_latest_run",
    )

    assert [window["label"] for window in payload["windows"]] == ["yesterday", "today"]
    assert all(window["dsl"].count("@B:FCST_TWN_PHY;") == 1 for window in payload["windows"])
    assert "@WIN:yesterday|2026-07-03T00:00:00|2026-07-03T23:59:59;" in payload["windows"][0]["dsl"]
    assert "@WIN:today|2026-07-04T00:00:00|2026-07-04T23:59:59;" in payload["windows"][1]["dsl"]


def test_area_risk_cache_reuses_product_bundle_and_score_details(monkeypatch):
    calls = {"bundle": 0, "score": 0}
    lat = np.array([0.0], dtype=float)
    lon = np.array([0.0], dtype=float)

    def fake_bundle(root, run_time, forecast_hour):
        calls["bundle"] += 1
        return {"cape": np.array([[1000.0]], dtype=float)}, lat, lon, ["source"]

    def fake_score_details(fields, thresholds):
        calls["score"] += 1
        return {"scores": {}, "factors": {}, "quality": {}}

    monkeypatch.setattr(area_risk_mod, "_risk_input_bundle", fake_bundle)
    monkeypatch.setattr(area_risk_mod, "multi_hazard_score_details", fake_score_details)
    monkeypatch.setattr(area_risk_mod, "load_thresholds", lambda: {})

    risk_input_cache = {}
    score_details_cache = {}
    for _idx in range(2):
        area_risk_mod.evaluate_area_risks(
            root=Path("/tmp/nafp"),
            run_time=datetime(2026, 7, 4, 8),
            forecast_hours=[3],
            towns=[],
            risk_input_cache=risk_input_cache,
            score_details_cache=score_details_cache,
        )

    assert calls == {"bundle": 1, "score": 1}
