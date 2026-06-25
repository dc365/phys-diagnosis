from __future__ import annotations

import numpy as np

from weather_diag.features.front import detect_front_candidates, front_candidate_fields


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
