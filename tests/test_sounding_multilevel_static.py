from __future__ import annotations

from pathlib import Path


def test_sounding_multilevel_module_exposes_elements_systems_and_risk_grids():
    text = Path("weather_diag/diagnosis/sounding_multilevel.py").read_text(encoding="utf-8")
    for token in [
        "build_multilevel_fields",
        "build_multilevel_systems",
        "build_multilevel_risk_fields",
        "augment_station_risks",
        "low_level_jet",
        "moisture_transport",
        "upper_jet",
        "front_candidate",
        "risk_hail_score",
        "risk_severe_convection_composite_score",
    ]:
        assert token in text


def test_sounding_api_exposes_multilevel_layers():
    text = Path("backend/app/api/v1/sounding.py").read_text(encoding="utf-8")
    for layer in [
        "wind850_speed",
        "rh850",
        "div850",
        "vort500",
        "wind300_speed",
        "shear_850_500",
        "risk_short_duration_heavy_rain_score",
        "risk_severe_convection_composite_score",
        '@router.get("/layers")',
    ]:
        assert layer in text


def test_sounding_optimized_uses_multilevel_augmenter():
    text = Path("weather_diag/diagnosis/sounding_optimized.py").read_text(encoding="utf-8")
    assert "from weather_diag.diagnosis.sounding_multilevel import augment_sounding_result" in text
    assert "augment_sounding_result(result, analysis_csv, lat, lon)" in text
    assert "multilevel fields" in text
