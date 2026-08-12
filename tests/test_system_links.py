from __future__ import annotations

from weather_diag.diagnosis.system_links import attach_feature_supporting_systems


def _polygon(coords, feature_type: str, feature_id: str):
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [coords]},
        "properties": {
            "id": feature_id,
            "feature_type": feature_type,
            "title": feature_type,
        },
    }


def _line(coords, feature_type: str, feature_id: str):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "id": feature_id,
            "feature_type": feature_type,
            "title": feature_type,
        },
    }


def test_attach_feature_supporting_systems_links_risk_area_to_relevant_overlap_systems():
    risk = _polygon([[0, 0], [3, 0], [3, 3], [0, 3], [0, 0]], "persistent_heavy_rain_risk", "risk-1")
    moisture = _polygon([[1, 1], [4, 1], [4, 4], [1, 4], [1, 1]], "moisture_convergence", "moisture-1")
    moisture_2 = _polygon([[0.5, 0.5], [2, 0.5], [2, 2], [0.5, 2], [0.5, 0.5]], "moisture_convergence", "moisture-2")
    jet = _line([[-1, 1.5], [2, 1.5], [5, 1.5]], "low_level_jet", "jet-1")
    distant = _polygon([[20, 20], [22, 20], [22, 22], [20, 22], [20, 20]], "high_pressure_divergence", "far-1")

    features = attach_feature_supporting_systems([risk, moisture, moisture_2, jet, distant])

    linked = features[0]["properties"]["supporting_systems"]
    assert [item["type"] for item in linked[:2]] == ["moisture_convergence", "low_level_jet"]
    assert [item["type"] for item in linked].count("moisture_convergence") == 1
    assert all(item["relation"] == "overlap" for item in linked[:2])
    assert all(item["distance_degrees"] == 0 for item in linked[:2])
    assert linked[0]["relevance"] >= linked[1]["relevance"]
    assert "空间重叠" in linked[0]["reason"]
    assert "supporting_systems" not in features[1]["properties"]


def test_attach_feature_supporting_systems_links_short_duration_heavy_rain_risk():
    risk = _polygon(
        [[110, 25], [114, 25], [114, 29], [110, 29], [110, 25]],
        "short_duration_heavy_rain_risk",
        "short-rain-1",
    )
    convergence = _polygon(
        [[111, 26], [113, 26], [113, 28], [111, 28], [111, 26]],
        "low_level_convergence",
        "conv-1",
    )
    jet = _line([[109, 27], [112, 27], [115, 27]], "low_level_jet", "jet-1")

    features = attach_feature_supporting_systems([risk, convergence, jet])

    linked = features[0]["properties"]["supporting_systems"]
    assert {item["type"] for item in linked} >= {"low_level_convergence", "low_level_jet"}
    assert all(item["relation"] == "overlap" for item in linked)
