from __future__ import annotations

import numpy as np

from weather_diag.features.front import detect_front_candidates, front_axis_components, front_candidate_fields


def _baroclinic_zone() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lat = np.linspace(25.0, 45.0, 41)
    lon = np.linspace(100.0, 125.0, 51)
    _, lat2d = np.meshgrid(lon, lat)
    t850 = 12.0 - 9.0 * np.tanh((lat2d - 35.0) / 1.3)
    return lat, lon, t850


def test_front_mask_requires_dynamic_support_when_wind_fields_are_available():
    lat, lon, t850 = _baroclinic_zone()
    lat2d = np.repeat(lat[:, None], lon.size, axis=1)
    quiet = np.zeros_like(t850)

    unsupported = front_candidate_fields(
        t850,
        quiet,
        quiet,
        lat,
        lon,
        {"front_candidate": {"temp_gradient_percentile": 70, "score_percentile": 70}},
        u850=quiet,
        v850=quiet,
    )

    v850 = -4.0 * np.tanh((lat2d - 35.0) / 2.0)
    div850 = -2.0e-5 * np.exp(-((lat2d - 35.0) / 1.8) ** 2)
    temp_adv850 = 1.0e-4 * np.exp(-((lat2d - 35.0) / 2.2) ** 2)

    supported = front_candidate_fields(
        t850,
        div850,
        temp_adv850,
        lat,
        lon,
        {"front_candidate": {"temp_gradient_percentile": 70, "score_percentile": 70}},
        u850=quiet,
        v850=v850,
    )

    assert not unsupported["mask"].any()
    assert supported["mask"].sum() > 80
    assert supported["support_count"].max() >= 2
    assert np.nanmax(supported["frontogenesis"]) > 0
    assert np.nanmax(supported["wind_deformation"]) > 0
    assert "cross_front_wind" in supported
    assert "temperature_advection" in supported


def test_front_detection_limits_output_to_strongest_objects():
    lat = np.linspace(20.0, 50.0, 121)
    lon = np.linspace(100.0, 130.0, 61)
    _, lat2d = np.meshgrid(lon, lat)
    t850 = np.zeros_like(lat2d)
    for center in [27.0, 35.0, 43.0]:
        t850 += -5.0 * np.tanh((lat2d - center) / 0.45)

    features = detect_front_candidates(
        t850,
        None,
        None,
        lat,
        lon,
        {
            "front_candidate": {
                "temp_gradient_percentile": 60,
                "score_percentile": 60,
                "min_area_grid_points": 5,
                "max_objects": 2,
            }
        },
    )

    assert len(features) == 2
    assert all(feature["properties"]["rank"] <= 2 for feature in features)


def _line_turn_angles(coords: list[list[float]]) -> np.ndarray:
    arr = np.asarray(coords, dtype=float)
    if arr.shape[0] < 3:
        return np.asarray([], dtype=float)
    vectors = np.diff(arr, axis=0)
    norms = np.linalg.norm(vectors, axis=1)
    unit_vectors = vectors[norms > 1.0e-9] / norms[norms > 1.0e-9, None]
    if unit_vectors.shape[0] < 2:
        return np.asarray([], dtype=float)
    dots = np.clip(np.sum(unit_vectors[:-1] * unit_vectors[1:], axis=1), -1.0, 1.0)
    return np.arccos(dots)


def test_front_axis_components_use_weather_chart_smoothness():
    lat = np.linspace(18.0, 55.0, 149)
    lon = np.linspace(70.0, 140.0, 141)
    lon2d, lat2d = np.meshgrid(lon, lat)
    center = 34.0 + 5.0 * np.sin((lon2d - 75.0) / 8.0) + 1.0 * np.sin((lon2d - 75.0) / 2.7)
    t850 = 20.0 - 12.0 * np.tanh((lat2d - center) / 0.8)
    thresholds = {
        "front_candidate": {
            "temp_gradient_percentile": 58,
            "score_percentile": 58,
            "min_area_grid_points": 20,
            "max_objects": 1,
        }
    }
    derived = front_candidate_fields(t850, None, None, lat, lon, thresholds)

    components = front_axis_components(
        derived,
        lat,
        lon,
        min_points=20,
        max_objects=1,
        thresholds=thresholds,
    )

    assert components
    coords = components[0]["line"]["coordinates"]
    angles = _line_turn_angles(coords)
    assert len(coords) >= 40
    assert float(np.nanpercentile(angles, 90)) < 0.30


def _typed_front(v_component: float):
    lat = np.linspace(25.0, 45.0, 81)
    lon = np.linspace(100.0, 125.0, 101)
    _, lat2d = np.meshgrid(lon, lat)
    t850 = 18.0 - 12.0 * np.tanh((lat2d - 35.0) / 0.9)
    u850 = np.zeros_like(t850)
    v850 = np.full_like(t850, v_component)
    div850 = -2.5e-5 * np.exp(-((lat2d - 35.0) / 1.5) ** 2)
    return detect_front_candidates(
        t850,
        div850,
        None,
        lat,
        lon,
        {
            "front_candidate": {
                "temp_gradient_percentile": 70,
                "score_percentile": 70,
                "min_area_grid_points": 8,
                "max_objects": 1,
                "cross_front_wind_min_ms": 1.0,
                "front_type_consistency_min": 0.5,
            }
        },
        u850=u850,
        v850=v850,
    )


def test_front_type_classifies_cold_front_by_cross_front_wind():
    features = _typed_front(-6.0)
    assert features
    props = features[0]["properties"]
    assert props["front_type"] == "cold_front"
    assert props["front_motion"] == "cold_air_advancing"
    assert props["cross_front_wind_mean_ms"] > 0
    assert props["temperature_advection_mean"] < 0


def test_front_type_classifies_warm_front_by_cross_front_wind():
    features = _typed_front(6.0)
    assert features
    props = features[0]["properties"]
    assert props["front_type"] == "warm_front"
    assert props["front_motion"] == "warm_air_overrunning"
    assert props["cross_front_wind_mean_ms"] < 0
    assert props["temperature_advection_mean"] > 0
