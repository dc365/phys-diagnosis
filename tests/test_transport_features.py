from __future__ import annotations

import numpy as np

from weather_diag.features.low_level_jet import detect_low_level_jet
from weather_diag.features.moisture_transport import detect_moisture_transport
from weather_diag.features.transport_objects import ranked_transport_components


def _transport_grid():
    lat = np.linspace(20.0, 45.0, 51)
    lon = np.linspace(100.0, 130.0, 61)
    lon2d, lat2d = np.meshgrid(lon, lat)
    return lat, lon, lon2d, lat2d


def test_ranked_transport_stream_axis_keeps_bbox_for_system_geometry():
    lat, lon, lon2d, lat2d = _transport_grid()
    mask = (np.abs(lat2d - 30.0) <= 1.0) & (lon2d >= 106.0) & (lon2d <= 124.0)
    value = np.where(mask, 20.0, 0.0)
    u = np.where(mask, 12.0, 0.0)
    v = np.zeros_like(u)

    [component] = ranked_transport_components(
        mask,
        lat,
        lon,
        value,
        min_points=8,
        max_objects=1,
        u=u,
        v=v,
    )

    assert component["axis_method"] == "streamline_axis"
    assert component["line"]["bbox"]


def test_low_level_jet_requires_wind_direction_coherence_and_limits_objects():
    lat, lon, lon2d, lat2d = _transport_grid()
    speed = np.zeros_like(lon2d) + 4.0
    moisture_flux = np.zeros_like(lon2d) + 10.0
    u = np.zeros_like(lon2d)
    v = np.zeros_like(lon2d)

    coherent_1 = (((lon2d - 108.0) / 2.0) ** 2 + ((lat2d - 29.0) / 2.0) ** 2) <= 1.0
    coherent_2 = (((lon2d - 121.0) / 2.3) ** 2 + ((lat2d - 37.0) / 1.8) ** 2) <= 1.0
    incoherent = (((lon2d - 126.0) / 1.6) ** 2 + ((lat2d - 26.0) / 1.6) ** 2) <= 1.0

    for mask, jet_speed in [(coherent_1, 20.0), (coherent_2, 18.0), (incoherent, 24.0)]:
        speed[mask] = jet_speed
        moisture_flux[mask] = 100.0
    u[coherent_1 | coherent_2] = speed[coherent_1 | coherent_2]
    flip = (np.indices(speed.shape)[1] % 2) == 0
    u[incoherent & flip] = speed[incoherent & flip]
    u[incoherent & ~flip] = -speed[incoherent & ~flip]

    features = detect_low_level_jet(
        speed,
        moisture_flux,
        lat,
        lon,
        {
            "low_level_jet": {
                "wind_speed_min_ms": 12.0,
                "moisture_flux_percentile": 60,
                "min_area_grid_points": 8,
                "min_direction_coherence": 0.75,
                "max_objects": 1,
            }
        },
        u850=u,
        v850=v,
    )

    assert len(features) == 1
    props = features[0]["properties"]
    assert props["rank"] == 1
    assert props["direction_coherence"] >= 0.75
    assert props["max_wind_ms"] < 24.0


def test_moisture_transport_keeps_coherent_ranked_transport_bands():
    lat, lon, lon2d, lat2d = _transport_grid()
    flux = np.zeros_like(lon2d) + 5.0
    u = np.zeros_like(lon2d)
    v = np.zeros_like(lon2d)

    band_1 = np.abs(lat2d - (28.0 + 0.08 * (lon2d - 100.0))) <= 1.1
    band_2 = np.abs(lat2d - (39.0 - 0.05 * (lon2d - 100.0))) <= 1.0
    noisy = (((lon2d - 124.0) / 1.7) ** 2 + ((lat2d - 24.0) / 1.7) ** 2) <= 1.0

    flux[band_1] = 120.0
    flux[band_2] = 95.0
    flux[noisy] = 140.0
    u[band_1 | band_2] = 10.0
    v[band_1] = 2.0
    v[band_2] = -2.0
    flip = (np.indices(flux.shape)[0] % 2) == 0
    u[noisy & flip] = 10.0
    u[noisy & ~flip] = -10.0

    features = detect_moisture_transport(
        flux,
        lat,
        lon,
        {
            "moisture_transport": {
                "flux_percentile": 85,
                "min_area_grid_points": 8,
                "min_direction_coherence": 0.75,
                "max_objects": 2,
            }
        },
        u850=u,
        v850=v,
    )

    assert len(features) == 2
    assert [feature["properties"]["rank"] for feature in features] == [1, 2]
    assert all(feature["properties"]["direction_coherence"] >= 0.75 for feature in features)
