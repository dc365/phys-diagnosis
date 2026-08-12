from __future__ import annotations

from weather_diag.diagnosis.conclusions import conclusions_from_chains, conclusions_from_features


def test_conclusions_from_chains_turns_evidence_and_system_links_into_duty_wording():
    conclusions = conclusions_from_chains(
        [
            {
                "target_type": "heavy_rain_potential",
                "level": "moderate",
                "score": 0.63,
                "dominant_evidence": [
                    {"signal": "low-level moisture", "value": "p75=14.55 g/kg"},
                    {"signal": "moisture transport", "value": "p90=143.56"},
                ],
                "linked_systems": [
                    {"type": "moisture_convergence", "relation": "overlap", "reason": "水汽辐合区与风险区空间重叠"},
                    {"type": "low_level_jet", "relation": "nearby", "reason": "低空急流位于风险区附近"},
                ],
            }
        ]
    )

    assert len(conclusions) == 1
    conclusion = conclusions[0]
    assert conclusion["target_type"] == "heavy_rain_potential"
    assert "强降水" in conclusion["headline"]
    assert "中等" in conclusion["headline"]
    assert any("主导证据" in item for item in conclusion["reasoning"])
    assert any("水汽辐合" in item and "低空急流" in item for item in conclusion["reasoning"])
    assert "实况" in conclusion["action_hint"]


def test_conclusions_from_features_summarizes_pipeline_risk_objects():
    conclusions = conclusions_from_features(
        [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {
                    "id": "persistent_heavy_rain_risk_001",
                    "feature_type": "persistent_heavy_rain_risk",
                    "hazard_type": "persistent_heavy_rain",
                    "risk_domain": ["precipitation"],
                    "risk_level": "high",
                    "max_value": 0.86,
                    "source_grid": "risk_persistent_heavy_rain_score",
                    "dominant_factors": [
                        {"label": "700hPa 上升运动", "mean_contribution": 0.17},
                        {"label": "水汽辐合", "mean_contribution": 0.16},
                    ],
                    "supporting_systems": [
                        {"type": "low_level_convergence", "relation": "overlap", "reason": "低层辐合区与风险区空间重叠"},
                        {"type": "low_level_jet", "relation": "overlap", "reason": "低空急流与风险区空间重叠"},
                    ],
                },
            }
        ]
    )

    assert conclusions[0]["target_type"] == "persistent_heavy_rain_risk"
    assert conclusions[0]["hazard_type"] == "persistent_heavy_rain"
    assert "高" in conclusions[0]["headline"]
    assert any("700hPa 上升运动" in item for item in conclusions[0]["reasoning"])
    assert any("低层辐合" in item for item in conclusions[0]["reasoning"])


def test_conclusions_from_features_uses_hazard_type_labels():
    conclusions = conclusions_from_features(
        [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {
                    "id": "short_duration_heavy_rain_risk_001",
                    "feature_type": "short_duration_heavy_rain_risk",
                    "hazard_type": "short_duration_heavy_rain",
                    "risk_domain": ["precipitation", "severe_convection"],
                    "risk_level": "high",
                    "max_value": 0.88,
                    "source_grid": "risk_short_duration_heavy_rain_score",
                    "dominant_factors": [{"label": "水汽辐合", "mean_contribution": 0.20}],
                    "supporting_systems": [{"type": "low_level_convergence", "relation": "overlap"}],
                },
            }
        ]
    )

    conclusion = conclusions[0]
    assert conclusion["hazard_type"] == "short_duration_heavy_rain"
    assert "短时强降水" in conclusion["headline"]
    assert conclusion["risk_domain"] == ["precipitation", "severe_convection"]
    assert conclusion["source_grid"] == "risk_short_duration_heavy_rain_score"
    assert any("水汽辐合" in item for item in conclusion["reasoning"])
