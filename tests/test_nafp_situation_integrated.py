from __future__ import annotations

from weather_diag.diagnosis import nafp_situation as base
from weather_diag.diagnosis.nafp_situation_integrated import _feature_to_system


def test_integrated_feature_string_evidence_is_system_evidence_payload():
    system = _feature_to_system(
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[100.0, 30.0], [101.0, 31.0]]},
            "properties": {
                "id": "upper_jet_200_001",
                "feature_type": "upper_jet",
                "title": "200hPa 高空急流轴",
                "confidence": 0.72,
                "evidence": ["高空强风带呈连续轴线结构"],
            },
        },
        1,
    )

    assert system is not None
    assert system["evidence"][0]["signal"] == "高空强风带呈连续轴线结构"
    annotated = base._annotate_system_display_metadata([system])
    assert annotated[0]["feature_type"] == "upper_jet"
    assert annotated[0]["primary"] is True
