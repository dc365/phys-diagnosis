from __future__ import annotations

from datetime import datetime
from pathlib import Path

from weather_diag.diagnosis.area_risk import area_risk_metadata
from weather_diag.mcp import area_risk_dsl as dsl_mod
from weather_diag.mcp.area_risk_dsl import (
    build_town_risk_dsl_response,
    resolve_forecast_hours_for_window,
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
    assert str(ecthin["root"]).endswith("/NAFP_ECTHIN_NC")
    assert cma_gfs["data_code"] == "NAFP_CMA_GFS_NC"
    assert str(cma_gfs["root"]).endswith("/NAFP_CMA_GFS_NC")


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
