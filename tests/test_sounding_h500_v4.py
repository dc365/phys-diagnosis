from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from weather_diag.features.sounding_trough_paths import (
    detect_sounding_multitrack_troughs,
    detect_south_china_shear_system,
)


DATA_DIR = Path(
    "test_datas/regional_radiosonde_5N55N_50E160E_20260624_20260625"
)
REFERENCE_FILES = [
    "regional_radiosonde_5N55N_50E160E_20260624_08BJT.csv",
    "regional_radiosonde_5N55N_50E160E_20260624_20BJT.csv",
    "regional_radiosonde_5N55N_50E160E_20260625_08BJT.csv",
    "regional_radiosonde_5N55N_50E160E_20260625_20BJT.csv",
]


def _synthetic_multibranch_fields():
    lat = np.arange(5.0, 56.0, 1.0)
    lon = np.arange(50.0, 161.0, 1.0)
    lon2d, lat2d = np.meshgrid(lon, lat)
    z500 = 5900.0 - 5.8 * (lat2d - 20.0)

    central_axis = 103.0 + 2.0 * np.sin((lat2d - 30.0) / 18.0 * np.pi)
    z500 -= 60.0 * np.exp(-((lon2d - central_axis) / 2.2) ** 2) * np.exp(
        -((lat2d - 42.0) / 13.0) ** 4
    )

    center_lon, center_lat = 126.0, 40.0
    radius = ((lon2d - center_lon) / 4.5) ** 2 + ((lat2d - center_lat) / 5.5) ** 2
    z500 -= 120.0 * np.exp(-radius)
    wind_radius = ((lon2d - center_lon) / 7.0) ** 2 + ((lat2d - center_lat) / 7.0) ** 2
    u500 = -18.0 * (lat2d - center_lat) / 7.0 * np.exp(-wind_radius / 2.0)
    v500 = 18.0 * (lon2d - center_lon) / 7.0 * np.exp(-wind_radius / 2.0)
    return z500, u500, v500, lat, lon


def test_four_reference_sounding_cycles_are_available():
    assert set(REFERENCE_FILES) <= {
        path.name for path in DATA_DIR.glob("regional_radiosonde*.csv")
    }


def test_multitrack_detector_splits_closed_low_and_keeps_independent_height_valley():
    z500, u500, v500, lat, lon = _synthetic_multibranch_fields()
    systems = detect_sounding_multitrack_troughs(
        z500,
        u500,
        v500,
        lat,
        lon,
        support_distance_km=np.full_like(z500, 120.0),
        support_mask=np.ones_like(z500, dtype=bool),
    )

    sources = {item["candidate_source"] for item in systems}
    assert {
        "closed_low_south_branch",
        "closed_low_north_branch",
        "dynamic_height_valley",
    } <= sources
    assert all(item["method"] == "sounding_multitrack_axis_v4" for item in systems)


def test_south_china_detector_outputs_shear_not_trough():
    lat = np.arange(5.0, 56.0, 1.0)
    lon = np.arange(50.0, 161.0, 1.0)
    lon2d, lat2d = np.meshgrid(lon, lat)
    axis = 108.0 + 0.08 * (lat2d - 20.0)
    z500 = 5880.0 - 4.8 * (lat2d - 20.0)
    u500 = 8.0 * np.tanh((lon2d - axis) / 1.6) + 3.0
    v500 = 7.0 - 4.0 * np.tanh((lon2d - axis) / 1.6)

    system = detect_south_china_shear_system(
        z500,
        u500,
        v500,
        lat,
        lon,
        support_distance_km=np.full_like(z500, 120.0),
        support_mask=np.ones_like(z500, dtype=bool),
    )

    assert system is not None
    assert system["feature_type"] == "shear_line"
    assert system["candidate_source"] == "south_china_588_deformation_track"
    coordinates = np.asarray(system["geometry"]["coordinates"], dtype=float)
    assert float(np.ptp(coordinates[:, 1])) >= 6.0
    assert 104.0 <= float(np.nanmean(coordinates[:, 0])) <= 115.0


@pytest.mark.parametrize("filename", REFERENCE_FILES)
def test_all_four_cycles_use_multitrack_troughs_and_independent_hainan_shear(filename: str):
    from weather_diag.diagnosis.sounding_optimized import diagnose_sounding_situation

    result = diagnose_sounding_situation(DATA_DIR / filename, pressure_level=500)
    troughs = [
        item for item in result["systems"] if item["feature_type"] == "trough_candidate"
    ]
    # The higher-latitude 24 June lows legitimately have one south branch,
    # while the 25 June closed lows split into north and south branches.
    assert len(troughs) >= 2
    assert all(item["method"] == "sounding_multitrack_axis_v4" for item in troughs)
    assert any(item["candidate_source"] == "dynamic_height_valley" for item in troughs)
    assert any(item["candidate_source"].startswith("closed_low_") for item in troughs)

    for item in troughs:
        coordinates = np.asarray(item["geometry"]["coordinates"], dtype=float)
        assert not np.any(
            (coordinates[:, 0] >= 104.0)
            & (coordinates[:, 0] <= 115.0)
            & (coordinates[:, 1] >= 13.0)
            & (coordinates[:, 1] <= 25.0)
        )

    hainan_shear = [
        item
        for item in result["systems"]
        if item["feature_type"] == "shear_line"
        and item.get("candidate_source") == "south_china_588_deformation_track"
    ]
    assert hainan_shear



@pytest.mark.parametrize(
    "filename",
    [
        "regional_radiosonde_5N55N_50E160E_20260625_08BJT.csv",
        "regional_radiosonde_5N55N_50E160E_20260625_20BJT.csv",
    ],
)
def test_25_june_cycles_keep_two_distinct_closed_low_branches(filename: str):
    from weather_diag.diagnosis.sounding_optimized import diagnose_sounding_situation

    result = diagnose_sounding_situation(DATA_DIR / filename, pressure_level=500)
    sources = {
        item["candidate_source"]
        for item in result["systems"]
        if item["feature_type"] == "trough_candidate"
    }
    assert {"closed_low_south_branch", "closed_low_north_branch"} <= sources

def test_20260625_20bjt_has_two_distinct_northeast_closed_low_branches():
    from weather_diag.diagnosis.sounding_optimized import diagnose_sounding_situation

    result = diagnose_sounding_situation(
        DATA_DIR / "regional_radiosonde_5N55N_50E160E_20260625_20BJT.csv",
        pressure_level=500,
    )
    branches = {
        item["candidate_source"]: np.asarray(item["geometry"]["coordinates"], dtype=float)
        for item in result["systems"]
        if item["feature_type"] == "trough_candidate"
        and item["candidate_source"] in {
            "closed_low_south_branch",
            "closed_low_north_branch",
        }
    }
    assert {"closed_low_south_branch", "closed_low_north_branch"} <= set(branches)
    south = branches["closed_low_south_branch"]
    north = branches["closed_low_north_branch"]
    assert float(np.nanmin(south[:, 1])) <= 31.0
    assert float(np.nanmax(north[:, 1])) >= 45.0
    assert float(np.nanmax(south[:, 1])) <= float(np.nanmin(north[:, 1])) + 1.5
