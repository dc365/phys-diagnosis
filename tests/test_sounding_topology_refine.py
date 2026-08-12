from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString

from weather_diag.features.sounding_topology_refine import (
    resolve_trough_shear_topology,
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


def _coordinates(system: dict) -> np.ndarray:
    return np.asarray((system.get("geometry") or {}).get("coordinates") or [], dtype=float)


def _project(coordinates: np.ndarray, reference_lat: float) -> np.ndarray:
    x_scale = 111.32 * max(float(np.cos(np.deg2rad(reference_lat))), 0.20)
    return np.column_stack([coordinates[:, 0] * x_scale, coordinates[:, 1] * 111.32])


def _lines_cross(first: dict, second: dict) -> bool:
    first_coordinates = _coordinates(first)
    second_coordinates = _coordinates(second)
    reference_lat = float(
        np.nanmedian(np.concatenate([first_coordinates[:, 1], second_coordinates[:, 1]]))
    )
    return LineString(_project(first_coordinates, reference_lat)).crosses(
        LineString(_project(second_coordinates, reference_lat))
    )


def test_x_crossing_is_converted_to_a_trough_endpoint_junction():
    trough = {
        "id": "trough-001",
        "feature_type": "trough_candidate",
        "candidate_source": "closed_low_south_branch",
        "geometry_refinement_version": "sounding_z500_geometry_v5",
        "path_metrics": {"height_evidence_mean": 0.72},
        "geometry": {
            "type": "line",
            "coordinates": [[110.0, 30.0], [110.0, 45.0]],
        },
    }
    shear = {
        "id": "shear-001",
        "feature_type": "shear_line",
        "geometry": {
            "type": "line",
            "coordinates": [
                [100.0, 34.0],
                [105.0, 37.0],
                [110.0, 40.0],
                [115.0, 43.0],
                [120.0, 46.0],
            ],
        },
        "evidence": [],
    }
    lat = np.arange(20.0, 56.0, 1.0)
    lon = np.arange(80.0, 141.0, 1.0)
    shape = (lat.size, lon.size)
    output = resolve_trough_shear_topology(
        [trough],
        [shear],
        z500=np.full(shape, 5700.0),
        u500=np.repeat(np.linspace(-10.0, 10.0, lon.size)[None, :], lat.size, axis=0),
        v500=np.full(shape, 5.0),
        lat=lat,
        lon=lon,
        support_distance_km=np.full(shape, 100.0),
        support_mask=np.ones(shape, dtype=bool),
    )

    assert len(output) == 1
    resolved = output[0]
    assert resolved["topology_resolution"] == "terminate_shear_at_z500_trough"
    assert resolved["topology_metrics"]["crossing_count_before"] == 1
    assert resolved["topology_metrics"]["retained_length_km"] < resolved["topology_metrics"]["original_length_km"]
    assert not _lines_cross(trough, resolved)

    trough_line = LineString(_project(_coordinates(trough), 40.0))
    resolved_line = LineString(_project(_coordinates(resolved), 40.0))
    assert resolved_line.distance(trough_line) < 1.0e-6


def test_parallel_shear_duplicate_is_suppressed():
    trough = {
        "id": "trough-001",
        "feature_type": "trough_candidate",
        "candidate_source": "dynamic_height_valley",
        "path_metrics": {"height_evidence_mean": 0.55},
        "geometry": {
            "type": "line",
            "coordinates": [[110.0, 30.0], [110.0, 48.0]],
        },
    }
    shear = {
        "id": "shear-001",
        "feature_type": "shear_line",
        "geometry": {
            "type": "line",
            "coordinates": [[110.5, 31.0], [110.4, 36.0], [110.6, 42.0], [110.5, 47.0]],
        },
    }

    assert resolve_trough_shear_topology([trough], [shear]) == []


@pytest.mark.parametrize("filename", REFERENCE_FILES)
def test_real_sounding_cycles_have_no_interior_trough_shear_crossings(filename: str):
    from weather_diag.diagnosis.sounding_optimized import diagnose_sounding_situation

    result = diagnose_sounding_situation(DATA_DIR / filename, pressure_level=500)
    troughs = [
        item for item in result["systems"] if item.get("feature_type") == "trough_candidate"
    ]
    shears = [
        item
        for item in result["systems"]
        if item.get("feature_type") in {"shear_line", "front_with_shear"}
    ]
    assert troughs
    assert shears
    assert not any(_lines_cross(trough, shear) for trough in troughs for shear in shears)


def test_20260625_20bjt_applies_topology_resolution_to_conflicting_shear():
    from weather_diag.diagnosis.sounding_optimized import diagnose_sounding_situation

    result = diagnose_sounding_situation(
        DATA_DIR / "regional_radiosonde_5N55N_50E160E_20260625_20BJT.csv",
        pressure_level=500,
    )
    resolved = [
        item
        for item in result["systems"]
        if item.get("feature_type") in {"shear_line", "front_with_shear"}
        and item.get("topology_refinement_version") == "sounding_trough_shear_topology_v6"
    ]
    assert resolved
    assert all(item.get("topology_resolution") == "terminate_shear_at_z500_trough" for item in resolved)
