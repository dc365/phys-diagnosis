from __future__ import annotations

import json
from datetime import datetime

import pytest

from weather_diag.mcp import area_risk_dsl_mcp
from weather_diag.mcp import observed_sounding


def _sample_sounding(data_time: str = "2026-07-09 08:00:00") -> dict:
    return {
        "msg": "success",
        "stationCode": "58847",
        "dataList": [
            {
                "dataTime": data_time,
                "data": {
                    "CT": [28.6],
                    "CTD": [26.020468],
                    "ZT": [28.6],
                    "RH": [85.0],
                    "ZP": [1000],
                    "WIND_P": [1000],
                    "WIND_VALUE": [[341.0, 0.6]],
                    "heightPoints": {
                        "CAPE": 2951,
                        "CIN": 0,
                        "K": 36,
                        "SI": -4.2,
                        "DCAPE": 1100,
                        "SRH": 160,
                        "SHR6KM": 18,
                    },
                    "temPoints": [{"hPa": 531, "name": "0"}],
                },
            }
        ],
    }


def test_observed_sounding_time_rule_uses_latest_real_observation():
    assert observed_sounding.select_observation_time(datetime(2026, 7, 9, 7, 59)) == datetime(2026, 7, 8, 20)
    assert observed_sounding.select_observation_time(datetime(2026, 7, 9, 8, 0)) == datetime(2026, 7, 9, 8)
    assert observed_sounding.select_observation_time(datetime(2026, 7, 9, 19, 59)) == datetime(2026, 7, 9, 8)
    assert observed_sounding.select_observation_time(datetime(2026, 7, 9, 20, 0)) == datetime(2026, 7, 9, 20)


def test_observed_sounding_payload_normalizes_station_profile(monkeypatch):
    sample = _sample_sounding()

    monkeypatch.setattr(observed_sounding, "fetch_station_payload", lambda config, station_code, obs_time: sample)

    payload = observed_sounding.get_observed_sounding_payload(station_code="58847", now=datetime(2026, 7, 9, 9))

    assert payload["request"]["observation_time"] == "2026-07-09T08:00:00"
    assert payload["request"]["station_codes"] == ["58847"]
    assert "time_rule" not in payload["request"]
    assert "time_source" not in payload["request"]
    assert "response_guide" not in payload
    assert "supported_stations" not in payload
    station = payload["stations"][0]
    assert station["station_code"] == "58847"
    assert station["station_name"] == "福州站"
    assert station["data_time"] == "2026-07-09 08:00:00"
    assert "curves" not in station
    assert "winds" not in station
    assert "field_mapping" not in station
    assert "profile_level_count" not in station
    assert "temperature_feature_points" not in station
    assert station["height_points"]["CAPE"] == 2951
    assert station["height_points"]["CIN"] == 0
    diagnoses = {item["field"]: item for item in station["physical_diagnoses"]}
    assert {"CAPE", "CIN", "K", "SI", "DCAPE", "SRH", "SHR6KM"} <= set(diagnoses)
    assert diagnoses["CAPE"]["support_level"] == "high"
    assert diagnoses["CIN"]["support_level"] == "high"
    assert diagnoses["K"]["support_level"] == "high"
    assert diagnoses["SI"]["support_level"] == "high"
    assert diagnoses["DCAPE"]["support_level"] == "high"
    assert diagnoses["SRH"]["support_level"] == "watch"
    assert diagnoses["SHR6KM"]["support_level"] == "watch"
    cape_evidence = diagnoses["CAPE"]["evidence_chain"][0]
    assert cape_evidence["source"] == "heightPoints.CAPE"
    assert cape_evidence["thresholds"] == {"watch": 1000, "high": 2000}
    assert station["physical_diagnosis_summary"]["high_count"] == 5
    assert station["physical_diagnosis_summary"]["watch_count"] == 2
    assert station["weather_diagnosis"]["description"]
    assert station["weather_diagnosis"]["evidence_fields"] == ["CAPE", "CIN", "K", "SI", "DCAPE", "SRH", "SHR6KM"]
    assert "source_url" not in json.dumps(payload)
    assert "password" not in json.dumps(payload)


def test_observed_sounding_payload_uses_specified_observation_time(monkeypatch):
    captured = {}

    def fake_fetch(config, station_code, obs_time):
        captured["obs_time"] = obs_time
        return _sample_sounding("2026-07-09 20:00:00")

    monkeypatch.setattr(observed_sounding, "fetch_station_payload", fake_fetch)

    payload = observed_sounding.get_observed_sounding_payload(
        station_code="58847",
        observation_time="2026-07-09 20:00:00",
        now=datetime(2026, 7, 9, 9),
    )

    assert captured["obs_time"] == datetime(2026, 7, 9, 20)
    assert payload["request"]["observation_time"] == "2026-07-09T20:00:00"
    assert "time_source" not in payload["request"]
    assert "time_rule" not in payload["request"]
    assert payload["stations"][0]["data_time"] == "2026-07-09 20:00:00"


def test_observed_sounding_test_mode_reads_station_file(monkeypatch, tmp_path):
    test_file = tmp_path / "sktk_58847.json"
    test_file.write_text(json.dumps(_sample_sounding("2026-07-09 20:00:00"), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("WEATHER_DIAG_SOUNDING_TEST_MODE", "1")
    monkeypatch.setenv("WEATHER_DIAG_SOUNDING_TEST_DATA_TEMPLATE", str(tmp_path / "sktk_{station}.json"))
    monkeypatch.setattr(observed_sounding, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network should not be used")))

    payload = observed_sounding.get_observed_sounding_payload(
        station_code="58847",
        observation_time="2026-07-09 20:00:00",
    )

    assert payload["failures"] == []
    assert payload["stations"][0]["data_time"] == "2026-07-09 20:00:00"
    assert payload["stations"][0]["height_points"]["CAPE"] == 2951


def test_observed_sounding_supported_station_names():
    config = observed_sounding.load_observed_sounding_config()

    names_by_code = {code: meta["name"] for code, meta in config["stations"].items()}
    assert names_by_code == {"58847": "福州站", "59134": "厦门站", "58725": "南平邵武站"}


def test_observed_sounding_rejects_unsupported_station():
    with pytest.raises(ValueError, match="unsupported sounding station"):
        observed_sounding.get_observed_sounding_payload(station_code="00000", now=datetime(2026, 7, 9, 9))


def test_observed_sounding_mcp_wrapper(monkeypatch):
    captured = {}

    def fake_payload(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(area_risk_dsl_mcp, "get_observed_sounding_payload", fake_payload)

    response = area_risk_dsl_mcp.get_observed_sounding(station_code="58847", observation_time="2026-07-09 20:00:00")

    assert response == {"code": 0, "msg": "success", "data": {"ok": True}}
    assert captured["station_code"] == "58847"
    assert captured["observation_time"] == "2026-07-09 20:00:00"
    assert "天气诊断" in (area_risk_dsl_mcp.get_observed_sounding.__doc__ or "")


def test_observed_sounding_mcp_error_omits_response_guide(monkeypatch):
    monkeypatch.setattr(area_risk_dsl_mcp, "get_observed_sounding_payload", lambda **kwargs: (_ for _ in ()).throw(ValueError("boom")))

    response = area_risk_dsl_mcp.get_observed_sounding(station_code="58847")

    assert response["code"] == 500
    assert response["data"] == {"error": "boom"}
