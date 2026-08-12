# Multi-Hazard Risk Grids Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split risk diagnosis from two broad potential fields into multiple continuous risk-grid fields and multi-label risk conclusions while preserving current weather-system and API compatibility.

**Architecture:** Add a shared risk taxonomy first, then generate one continuous grid per hazard type. Convert those grids into risk GeoJSON/features, API risk diagnoses, point summaries, and frontend grouped views. Keep legacy `heavy_rain_risk`, `convection_risk`, `heavy_rain_potential`, and `convection_potential` during the migration so current tests and clients keep working.

**Tech Stack:** Python 3.11, NumPy, xarray/NetCDF, FastAPI, pytest, static JavaScript, Node test runner.

---

## Scope

Build:
- Continuous `0-1` score grids for individual risk categories.
- Shared taxonomy metadata for `risk_domain`, `hazard_type`, labels, layers, feature types, and legacy mappings.
- `risk_diagnoses` objects derived from score grids and evidence chains.
- Backward-compatible API/frontend behavior.
- Tests and docs that lock the new contract.

Not building:
- Radar nowcasting or radar echo morphology.
- Operational tornado probability. First version outputs only `rotating_storm_or_supercell` potential.
- A new storage service, database, queue, or new runtime.
- Removal of old two-field risk outputs.

## Data Contract

Risk score grids:

```text
risk_persistent_heavy_rain_score(lat, lon)
risk_short_duration_heavy_rain_score(lat, lon)
risk_thunderstorm_gale_score(lat, lon)
risk_hail_score(lat, lon)
risk_rotating_storm_score(lat, lon)
risk_severe_convection_composite_score(lat, lon)
risk_precipitation_composite_score(lat, lon)
```

Risk diagnosis object:

```json
{
  "risk_id": "risk-short_duration_heavy_rain-001",
  "hazard_type": "short_duration_heavy_rain",
  "risk_domain": ["precipitation", "severe_convection"],
  "mechanism_tags": ["convective", "low_level_convergence", "moisture_convergence"],
  "convective_mode": "multicell_possible",
  "level": "high",
  "score": 0.82,
  "confidence": 0.78,
  "geometry": {"type": "polygon", "bbox": [105.0, 25.0, 112.0, 31.0], "coordinates": []},
  "dominant_factors": [],
  "linked_systems": [],
  "source_grid": "risk_short_duration_heavy_rain_score",
  "source_chain_ids": ["evidence-heavy-rain-potential", "evidence-convection-potential"]
}
```

## File Map

- Create: `weather_diag/diagnosis/risk_taxonomy.py`
  - Owns risk category metadata and legacy mappings.
- Modify: `weather_diag/features/risk.py`
  - Adds hazard score-grid builders and risk-feature conversion helpers.
- Modify: `weather_diag/pipeline.py`
  - Writes new score variables to `diagnostics.nc`, emits new risk features, keeps legacy risk features.
- Modify: `weather_diag/diagnosis/nafp_layers.py`
  - Serves dynamic NAFP layers for the new risk grids.
- Modify: `weather_diag/diagnosis/nafp_situation.py`
  - Adds `risk_diagnoses` to area diagnosis.
- Modify: `weather_diag/diagnosis/point.py`
  - Adds point-level risk score summaries using the same taxonomy.
- Modify: `weather_diag/diagnosis/conclusions.py`
  - Generates conclusions from `hazard_type` and keeps legacy fallback.
- Modify: `weather_diag/diagnosis/system_links.py`
  - Links new risk feature types to supporting weather systems.
- Modify: `weather_diag/diagnosis/algorithm_rules.py`
  - Adds catalog and threshold-matrix entries for new hazards.
- Modify: `configs/thresholds.yaml`
  - Adds product-layer weights and thresholds for each hazard score.
- Modify: `configs/layers.yaml`
  - Exposes new risk-grid layers.
- Modify: `backend/app/main.py`
  - Keeps old analysis endpoints and adds risk-type aware counts where needed.
- Modify: `docs/api.md`, `docs/algorithms.md`
  - Documents the new contract.
- Modify: `frontend/map.js`, `frontend/maplibre-utils.js`
  - Adds grouped risk display and layer recommendations.
- Test: `tests/test_risk_taxonomy.py`
- Test: `tests/test_risk_features.py`
- Test: `tests/test_diagnosis_conclusions.py`
- Test: `tests/test_nafp_situation.py`
- Test: `tests/test_nafp_point_diagnosis.py`
- Test: `tests/test_nafp_layers.py`
- Test: `tests/frontend-maplibre-utils.test.js`
- Test: `tests/frontend-map-point-diagnosis.test.js`

## Task 1: Baseline Safety And Contract Tests

**Files:**
- Create: `tests/test_risk_taxonomy.py`
- Modify later only after this task passes.

- [ ] **Step 1: Record current dirty worktree**

Run:

```bash
git status --short
```

Expected: many existing modified/untracked files may appear. Do not revert them. During execution, stage only files listed in each task.

- [ ] **Step 2: Write failing taxonomy contract tests**

Create `tests/test_risk_taxonomy.py`:

```python
from __future__ import annotations

from weather_diag.diagnosis.risk_taxonomy import (
    HAZARD_TYPES,
    feature_type_for_hazard,
    hazard_from_feature_type,
    legacy_target_hazards,
    risk_grid_for_hazard,
)


def test_short_duration_heavy_rain_is_cross_domain():
    meta = HAZARD_TYPES["short_duration_heavy_rain"]

    assert meta["label"] == "短时强降水"
    assert meta["risk_domain"] == ["precipitation", "severe_convection"]
    assert meta["score_grid"] == "risk_short_duration_heavy_rain_score"
    assert meta["feature_type"] == "short_duration_heavy_rain_risk"


def test_hazard_feature_and_grid_mappings_are_bidirectional():
    assert risk_grid_for_hazard("hail") == "risk_hail_score"
    assert feature_type_for_hazard("thunderstorm_gale") == "thunderstorm_gale_risk"
    assert hazard_from_feature_type("rotating_storm_risk") == "rotating_storm_or_supercell"


def test_legacy_targets_expand_without_mutating_old_contract():
    assert legacy_target_hazards("heavy_rain_potential") == [
        "persistent_heavy_rain",
        "short_duration_heavy_rain",
    ]
    assert legacy_target_hazards("convection_potential") == [
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    ]
```

- [ ] **Step 3: Run the failing test**

Run:

```bash
python -m pytest tests/test_risk_taxonomy.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'weather_diag.diagnosis.risk_taxonomy'`.

## Task 2: Add Shared Risk Taxonomy

**Files:**
- Create: `weather_diag/diagnosis/risk_taxonomy.py`
- Test: `tests/test_risk_taxonomy.py`

- [ ] **Step 1: Implement taxonomy module**

Create `weather_diag/diagnosis/risk_taxonomy.py` with these exact public names:

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any


RISK_DOMAINS = {
    "precipitation": "强降水风险",
    "severe_convection": "强对流风险",
}


HAZARD_TYPES: dict[str, dict[str, Any]] = {
    "persistent_heavy_rain": {
        "label": "持续性强降水",
        "risk_domain": ["precipitation"],
        "score_grid": "risk_persistent_heavy_rain_score",
        "feature_type": "persistent_heavy_rain_risk",
        "mechanism_tags": ["persistent_moisture_transport", "large_scale_lift"],
    },
    "short_duration_heavy_rain": {
        "label": "短时强降水",
        "risk_domain": ["precipitation", "severe_convection"],
        "score_grid": "risk_short_duration_heavy_rain_score",
        "feature_type": "short_duration_heavy_rain_risk",
        "mechanism_tags": ["convective", "low_level_convergence", "moisture_convergence"],
    },
    "thunderstorm_gale": {
        "label": "雷暴大风",
        "risk_domain": ["severe_convection"],
        "score_grid": "risk_thunderstorm_gale_score",
        "feature_type": "thunderstorm_gale_risk",
        "mechanism_tags": ["downdraft_potential", "deep_layer_shear"],
    },
    "hail": {
        "label": "冰雹",
        "risk_domain": ["severe_convection"],
        "score_grid": "risk_hail_score",
        "feature_type": "hail_risk",
        "mechanism_tags": ["strong_updraft", "deep_layer_shear", "cold_mid_level"],
    },
    "rotating_storm_or_supercell": {
        "label": "旋转风暴/超级单体潜势",
        "risk_domain": ["severe_convection"],
        "score_grid": "risk_rotating_storm_score",
        "feature_type": "rotating_storm_risk",
        "mechanism_tags": ["deep_layer_shear", "low_level_rotation"],
    },
    "severe_convection_composite": {
        "label": "强对流综合风险",
        "risk_domain": ["severe_convection"],
        "score_grid": "risk_severe_convection_composite_score",
        "feature_type": "severe_convection_composite_risk",
        "mechanism_tags": ["composite"],
    },
}


DOMAIN_COMPOSITE_GRIDS = {
    "precipitation": "risk_precipitation_composite_score",
    "severe_convection": "risk_severe_convection_composite_score",
}


LEGACY_TARGET_HAZARDS = {
    "heavy_rain_potential": ["persistent_heavy_rain", "short_duration_heavy_rain"],
    "convection_potential": [
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    ],
    "heavy_rain_risk": ["persistent_heavy_rain", "short_duration_heavy_rain"],
    "convection_risk": [
        "short_duration_heavy_rain",
        "thunderstorm_gale",
        "hail",
        "rotating_storm_or_supercell",
        "severe_convection_composite",
    ],
}


def hazard_metadata(hazard_type: str) -> dict[str, Any]:
    return deepcopy(HAZARD_TYPES[hazard_type])


def risk_grid_for_hazard(hazard_type: str) -> str:
    return str(HAZARD_TYPES[hazard_type]["score_grid"])


def feature_type_for_hazard(hazard_type: str) -> str:
    return str(HAZARD_TYPES[hazard_type]["feature_type"])


def hazard_from_feature_type(feature_type: str) -> str | None:
    for hazard_type, meta in HAZARD_TYPES.items():
        if meta["feature_type"] == feature_type:
            return hazard_type
    return None


def legacy_target_hazards(target_type: str) -> list[str]:
    return list(LEGACY_TARGET_HAZARDS.get(target_type, []))
```

- [ ] **Step 2: Verify taxonomy tests pass**

Run:

```bash
python -m pytest tests/test_risk_taxonomy.py -q
```

Expected: `3 passed`.

- [ ] **Step 3: Commit this isolated contract**

Run:

```bash
git add weather_diag/diagnosis/risk_taxonomy.py tests/test_risk_taxonomy.py
git commit -m "feat: add multi-hazard risk taxonomy"
```

Expected: commit succeeds if the execution branch is clean enough. If unrelated dirty files block committing, skip the commit and note the blocker in the task log.

## Task 3: Add Hazard Score Grid Builders

**Files:**
- Modify: `weather_diag/features/risk.py`
- Modify: `configs/thresholds.yaml`
- Test: `tests/test_risk_features.py`

- [ ] **Step 1: Add failing score-grid tests**

Append to `tests/test_risk_features.py`:

```python
from weather_diag.features.risk import multi_hazard_score_details


def test_multi_hazard_score_details_outputs_independent_score_grids():
    lat, lon, lon2d, lat2d = _risk_grid()
    core = np.exp(-(((lon2d - 115.0) / 3.0) ** 2 + ((lat2d - 29.0) / 2.0) ** 2))
    fields = {
        "moisture_flux": 100.0 * core,
        "moisture_convergence": 5.0 * core,
        "div850": -2.5e-5 * core,
        "omega700": -0.8 * core,
        "k_index": 34.0 * core,
        "cape": 1600.0 * core,
        "precipitation": 35.0 * core,
        "cin": -20.0 - 100.0 * (1.0 - core),
        "shear_0_6km": 24.0 * core,
        "dcape": 900.0 * core,
        "srh": 120.0 * core,
        "shear_0_1km": 8.0 * core,
        "li": -5.0 * core,
    }

    details = multi_hazard_score_details(fields, {
        "persistent_heavy_rain_risk": {"weights": {"moisture_flux": 0.22, "moisture_convergence": 0.24, "low_level_convergence": 0.16, "upward_motion": 0.20, "precipitation": 0.18}},
        "short_duration_heavy_rain_risk": {"weights": {"moisture_flux": 0.16, "moisture_convergence": 0.22, "low_level_convergence": 0.20, "k_index": 0.18, "cape": 0.18, "precipitation": 0.06}},
        "thunderstorm_gale_risk": {"weights": {"cape": 0.20, "dcape": 0.24, "shear_0_6km": 0.22, "low_level_convergence": 0.12}},
        "hail_risk": {"weights": {"cape": 0.30, "shear_0_6km": 0.30, "li": 0.10}},
        "rotating_storm_risk": {"weights": {"cape": 0.22, "shear_0_6km": 0.24, "srh": 0.28, "shear_0_1km": 0.12}},
    })

    expected = {
        "risk_persistent_heavy_rain_score",
        "risk_short_duration_heavy_rain_score",
        "risk_thunderstorm_gale_score",
        "risk_hail_score",
        "risk_rotating_storm_score",
        "risk_severe_convection_composite_score",
        "risk_precipitation_composite_score",
    }
    assert expected <= set(details["scores"])
    assert details["scores"]["risk_short_duration_heavy_rain_score"].shape == lon2d.shape
    assert float(np.nanmax(details["scores"]["risk_precipitation_composite_score"])) > 0.5
    assert float(np.nanmax(details["scores"]["risk_severe_convection_composite_score"])) > 0.5
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
python -m pytest tests/test_risk_features.py::test_multi_hazard_score_details_outputs_independent_score_grids -q
```

Expected: FAIL with `ImportError` or `AttributeError` for `multi_hazard_score_details`.

- [ ] **Step 3: Implement `multi_hazard_score_details`**

In `weather_diag/features/risk.py`, add imports and helper specs. Reuse existing `_score_details`, `_identity_score`, `_positive_score`, `_negative_score`, and `_weak_inhibition`.

Required scoring specs:

```python
PERSISTENT_HEAVY_RAIN_SPECS = [
    {"factor": "moisture_flux", "field": "moisture_flux", "label": "水汽通量", "score": _identity_score},
    {"factor": "moisture_convergence", "field": "moisture_convergence", "label": "水汽辐合", "score": _positive_score},
    {"factor": "low_level_convergence", "field": "div850", "label": "低层辐合", "score": _negative_score},
    {"factor": "upward_motion", "field": "omega700", "label": "700hPa 上升运动", "score": _negative_score},
    {"factor": "precipitation", "field": "precipitation", "label": "模式降水", "score": _identity_score},
]

SHORT_DURATION_HEAVY_RAIN_SPECS = [
    {"factor": "moisture_flux", "field": "moisture_flux", "label": "水汽通量", "score": _identity_score},
    {"factor": "moisture_convergence", "field": "moisture_convergence", "label": "水汽辐合", "score": _positive_score},
    {"factor": "low_level_convergence", "field": "div850", "label": "低层辐合触发", "score": _negative_score},
    {"factor": "k_index", "field": "k_index", "label": "K 指数", "score": _identity_score},
    {"factor": "cape", "field": "cape", "label": "CAPE", "score": _identity_score},
    {"factor": "precipitation", "field": "precipitation", "label": "模式降水", "score": _identity_score},
]

THUNDERSTORM_GALE_SPECS = [
    {"factor": "cape", "field": "cape", "label": "CAPE", "score": _identity_score},
    {"factor": "dcape", "field": "dcape", "label": "DCAPE", "score": _identity_score},
    {"factor": "shear_0_6km", "field": "shear_0_6km", "label": "0-6km 风切变", "score": _identity_score},
    {"factor": "low_level_convergence", "field": "div850", "label": "低层触发", "score": _negative_score},
]

HAIL_SPECS = [
    {"factor": "cape", "field": "cape", "label": "CAPE", "score": _identity_score},
    {"factor": "shear_0_6km", "field": "shear_0_6km", "label": "0-6km 风切变", "score": _identity_score},
    {"factor": "li", "field": "li", "label": "抬升指数", "score": _negative_score},
]

ROTATING_STORM_SPECS = [
    {"factor": "cape", "field": "cape", "label": "CAPE", "score": _identity_score},
    {"factor": "shear_0_6km", "field": "shear_0_6km", "label": "0-6km 风切变", "score": _identity_score},
    {"factor": "srh", "field": "srh", "label": "SRH", "score": _identity_score},
    {"factor": "shear_0_1km", "field": "shear_0_1km", "label": "0-1km 风切变", "score": _identity_score},
]
```

Add function:

```python
def multi_hazard_score_details(fields: dict, thresholds: dict) -> dict:
    specs = {
        "risk_persistent_heavy_rain_score": ("persistent_heavy_rain_risk", PERSISTENT_HEAVY_RAIN_SPECS),
        "risk_short_duration_heavy_rain_score": ("short_duration_heavy_rain_risk", SHORT_DURATION_HEAVY_RAIN_SPECS),
        "risk_thunderstorm_gale_score": ("thunderstorm_gale_risk", THUNDERSTORM_GALE_SPECS),
        "risk_hail_score": ("hail_risk", HAIL_SPECS),
        "risk_rotating_storm_score": ("rotating_storm_risk", ROTATING_STORM_SPECS),
    }
    scores = {}
    factors = {}
    available_weights = {}
    for grid_name, (cfg_name, cfg_specs) in specs.items():
        details = _score_details(fields, thresholds.get(cfg_name, {}).get("weights", {}), cfg_specs)
        scores[grid_name] = details["score"]
        factors[grid_name] = details["factors"]
        available_weights[grid_name] = details["available_weight"]

    scores["risk_precipitation_composite_score"] = np.nanmax(
        np.stack([
            scores["risk_persistent_heavy_rain_score"],
            scores["risk_short_duration_heavy_rain_score"],
        ]),
        axis=0,
    )
    scores["risk_severe_convection_composite_score"] = np.nanmax(
        np.stack([
            scores["risk_short_duration_heavy_rain_score"],
            scores["risk_thunderstorm_gale_score"],
            scores["risk_hail_score"],
            scores["risk_rotating_storm_score"],
        ]),
        axis=0,
    )
    return {"scores": scores, "factors": factors, "available_weights": available_weights}
```

- [ ] **Step 4: Add thresholds**

In `configs/thresholds.yaml`, add keys:

```yaml
persistent_heavy_rain_risk:
  score_threshold: 0.60
  high_score_threshold: 0.75
  min_area_grid_points: 12
  max_objects: 8
  weights:
    moisture_flux: 0.22
    moisture_convergence: 0.24
    low_level_convergence: 0.16
    upward_motion: 0.20
    precipitation: 0.18

short_duration_heavy_rain_risk:
  score_threshold: 0.60
  high_score_threshold: 0.75
  min_area_grid_points: 10
  max_objects: 8
  weights:
    moisture_flux: 0.16
    moisture_convergence: 0.22
    low_level_convergence: 0.20
    k_index: 0.18
    cape: 0.18
    precipitation: 0.06

thunderstorm_gale_risk:
  score_threshold: 0.58
  high_score_threshold: 0.72
  min_area_grid_points: 10
  max_objects: 8
  weights:
    cape: 0.20
    dcape: 0.24
    shear_0_6km: 0.22
    low_level_convergence: 0.12

hail_risk:
  score_threshold: 0.58
  high_score_threshold: 0.72
  min_area_grid_points: 8
  max_objects: 8
  weights:
    cape: 0.30
    shear_0_6km: 0.30
    li: 0.10

rotating_storm_risk:
  score_threshold: 0.55
  high_score_threshold: 0.70
  min_area_grid_points: 8
  max_objects: 8
  weights:
    cape: 0.22
    shear_0_6km: 0.24
    srh: 0.28
    shear_0_1km: 0.12
```

- [ ] **Step 5: Run risk feature tests**

Run:

```bash
python -m pytest tests/test_risk_features.py -q
```

Expected: all tests in `tests/test_risk_features.py` pass.

## Task 4: Write New Risk Grids In Pipeline Products

**Files:**
- Modify: `weather_diag/pipeline.py`
- Modify: `configs/layers.yaml`
- Test: `tests/test_risk_features.py`

- [ ] **Step 1: Add failing pipeline assertions**

Append to `test_pipeline_risk_features_include_dominant_factor_evidence` in `tests/test_risk_features.py`:

```python
    diagnostics_path = load_analysis("risk_feature_details_demo", 24)["diagnostics"]
    assert diagnostics_path.endswith("diagnostics.nc")
```

Add a new test:

```python
def test_pipeline_writes_multi_hazard_risk_score_grids(tmp_path):
    source = create_demo_ecmwf_netcdf(tmp_path / "multi_hazard_demo.nc")
    diagnose_file(source, run_id="multi_hazard_risk_demo")
    ds = load_diagnostics("multi_hazard_risk_demo", 24)

    for name in [
        "risk_persistent_heavy_rain_score",
        "risk_short_duration_heavy_rain_score",
        "risk_thunderstorm_gale_score",
        "risk_hail_score",
        "risk_rotating_storm_score",
        "risk_severe_convection_composite_score",
        "risk_precipitation_composite_score",
    ]:
        assert name in ds
        assert ds[name].attrs["units"] == "0-1"
        assert float(ds[name].max()) <= 1.0
```

Import `load_diagnostics` at the top of the test file.

- [ ] **Step 2: Run the failing test**

Run:

```bash
python -m pytest tests/test_risk_features.py::test_pipeline_writes_multi_hazard_risk_score_grids -q
```

Expected: FAIL because the new variables are absent.

- [ ] **Step 3: Modify pipeline diagnostics writing**

In `weather_diag/pipeline.py`:

1. Import `multi_hazard_score_details`.
2. After current `heavy_rain_score_details` and `convection_score_details` are computed, call `multi_hazard_score_details` with the same field dictionary plus optional fields when available.
3. Add each returned score into `diag_vars` with attrs:

```python
attrs={"units": "0-1", "long_name": "<Chinese label from taxonomy>"}
```

Keep existing `heavy_rain_score` and `convection_score` variables unchanged.

- [ ] **Step 4: Add layers**

In `configs/layers.yaml`, add layer entries for each new grid. Use the existing risk-score layer style. Titles:

```yaml
risk_persistent_heavy_rain_score: 持续性强降水风险评分
risk_short_duration_heavy_rain_score: 短时强降水风险评分
risk_thunderstorm_gale_score: 雷暴大风风险评分
risk_hail_score: 冰雹风险评分
risk_rotating_storm_score: 旋转风暴/超级单体潜势评分
risk_severe_convection_composite_score: 强对流综合风险评分
risk_precipitation_composite_score: 强降水综合风险评分
```

- [ ] **Step 5: Run pipeline risk tests**

Run:

```bash
python -m pytest tests/test_risk_features.py -q
```

Expected: all risk tests pass.

## Task 5: Generate Multi-Hazard Risk Features And Risk Diagnoses

**Files:**
- Modify: `weather_diag/features/risk.py`
- Modify: `weather_diag/diagnosis/system_links.py`
- Modify: `weather_diag/analysis/report.py`
- Test: `tests/test_risk_features.py`
- Test: `tests/test_system_links.py`

- [ ] **Step 1: Add failing feature assertions**

In `tests/test_risk_features.py`, add:

```python
def test_pipeline_outputs_multi_hazard_risk_features(tmp_path):
    source = create_demo_ecmwf_netcdf(tmp_path / "multi_hazard_features.nc")
    diagnose_file(source, run_id="multi_hazard_features_demo")
    features = load_features("multi_hazard_features_demo", 24)["features"]
    feature_types = {feature["properties"]["feature_type"] for feature in features}

    assert "short_duration_heavy_rain_risk" in feature_types
    assert "severe_convection_composite_risk" in feature_types

    short_rain = next(
        feature for feature in features
        if feature["properties"]["feature_type"] == "short_duration_heavy_rain_risk"
    )
    props = short_rain["properties"]
    assert props["hazard_type"] == "short_duration_heavy_rain"
    assert props["risk_domain"] == ["precipitation", "severe_convection"]
    assert props["source_grid"] == "risk_short_duration_heavy_rain_score"
    assert props["dominant_factors"]
    assert "supporting_systems" in props
```

- [ ] **Step 2: Run the failing feature test**

Run:

```bash
python -m pytest tests/test_risk_features.py::test_pipeline_outputs_multi_hazard_risk_features -q
```

Expected: FAIL because new feature types are absent.

- [ ] **Step 3: Add feature builder**

In `weather_diag/features/risk.py`, add:

```python
def detect_hazard_risk_features(
    hazard_type: str,
    score: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    factor_details: dict | None = None,
) -> list[dict]:
    from weather_diag.diagnosis.risk_taxonomy import hazard_metadata

    meta = hazard_metadata(hazard_type)
    cfg = thresholds.get(meta["feature_type"], {})
    features = _ranked_risk_features(
        score,
        lat,
        lon,
        feature_type=meta["feature_type"],
        title=meta["label"] + "风险区",
        cfg=cfg,
        factor_details=factor_details,
        base_evidence=meta["label"] + "综合评分较高",
    )
    for feature in features:
        props = feature.setdefault("properties", {})
        props["hazard_type"] = hazard_type
        props["risk_domain"] = list(meta["risk_domain"])
        props["mechanism_tags"] = list(meta["mechanism_tags"])
        props["source_grid"] = meta["score_grid"]
    return features
```

- [ ] **Step 4: Modify pipeline to add hazard features**

In `weather_diag/pipeline.py`, after writing legacy risk features, iterate hazard scores:

```python
for hazard_type, score_grid in [
    ("persistent_heavy_rain", "risk_persistent_heavy_rain_score"),
    ("short_duration_heavy_rain", "risk_short_duration_heavy_rain_score"),
    ("thunderstorm_gale", "risk_thunderstorm_gale_score"),
    ("hail", "risk_hail_score"),
    ("rotating_storm_or_supercell", "risk_rotating_storm_score"),
    ("severe_convection_composite", "risk_severe_convection_composite_score"),
]:
    features.extend(
        detect_hazard_risk_features(
            hazard_type,
            multi_hazard_details["scores"][score_grid],
            lat,
            lon,
            thresholds,
            factor_details=multi_hazard_details["factors"].get(score_grid),
        )
    )
```

Do not remove `detect_heavy_rain_risk` or `detect_convection_risk`.

- [ ] **Step 5: Update system support mappings**

In `weather_diag/diagnosis/system_links.py`, extend:

```python
RISK_FEATURE_TO_CHAIN.update({
    "persistent_heavy_rain_risk": "heavy_rain_potential",
    "short_duration_heavy_rain_risk": "heavy_rain_potential",
    "thunderstorm_gale_risk": "convection_potential",
    "hail_risk": "convection_potential",
    "rotating_storm_risk": "convection_potential",
    "severe_convection_composite_risk": "convection_potential",
})
```

Add `SUPPORT_WEIGHTS` aliases by reusing heavy-rain weights for persistent/short rain and convection weights for the severe-convection hazards.

- [ ] **Step 6: Run feature and link tests**

Run:

```bash
python -m pytest tests/test_risk_features.py tests/test_system_links.py -q
```

Expected: all tests pass.

## Task 6: Add `risk_diagnoses` To NAFP Situation And Point Diagnosis

**Files:**
- Modify: `weather_diag/diagnosis/nafp_situation.py`
- Modify: `weather_diag/diagnosis/point.py`
- Test: `tests/test_nafp_situation.py`
- Test: `tests/test_nafp_point_diagnosis.py`

- [ ] **Step 1: Add failing area diagnosis tests**

Append to `tests/test_nafp_situation.py`:

```python
def test_nafp_situation_returns_multi_hazard_risk_diagnoses():
    result = diagnose_nafp_situation(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    hazards = {item["hazard_type"]: item for item in result["risk_diagnoses"]}
    assert "short_duration_heavy_rain" in hazards
    assert hazards["short_duration_heavy_rain"]["risk_domain"] == ["precipitation", "severe_convection"]
    assert hazards["short_duration_heavy_rain"]["source_chain_ids"]
    assert hazards["short_duration_heavy_rain"]["geometry"]["type"] == "polygon"
    assert hazards["severe_convection_composite"]["risk_domain"] == ["severe_convection"]
```

- [ ] **Step 2: Add failing point diagnosis tests**

Append to `tests/test_nafp_point_diagnosis.py`:

```python
def test_nafp_point_returns_multi_hazard_scores():
    result = diagnose_nafp_point(
        root=NAFP_SAMPLE_ROOT,
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
        lat=30.0,
        lon=115.0,
    )

    hazards = {item["hazard_type"]: item for item in result["risk_diagnoses"]}
    assert "short_duration_heavy_rain" in hazards
    assert hazards["short_duration_heavy_rain"]["risk_domain"] == ["precipitation", "severe_convection"]
    assert "score" in hazards["short_duration_heavy_rain"]
    assert "level" in hazards["short_duration_heavy_rain"]
```

- [ ] **Step 3: Run failing tests**

Run:

```bash
python -m pytest tests/test_nafp_situation.py::test_nafp_situation_returns_multi_hazard_risk_diagnoses tests/test_nafp_point_diagnosis.py::test_nafp_point_returns_multi_hazard_scores -q
```

Expected: FAIL because `risk_diagnoses` is absent.

- [ ] **Step 4: Implement chain-to-risk conversion**

In `weather_diag/diagnosis/nafp_situation.py`, add a helper:

```python
def risk_diagnoses_from_chains(evidence_chains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from weather_diag.diagnosis.risk_taxonomy import hazard_metadata, legacy_target_hazards

    by_target = {chain.get("target_type"): chain for chain in evidence_chains}
    out = []
    for target_type, chain in by_target.items():
        for hazard_type in legacy_target_hazards(str(target_type)):
            meta = hazard_metadata(hazard_type)
            item = {
                "risk_id": f"risk-{hazard_type}",
                "hazard_type": hazard_type,
                "label": meta["label"],
                "risk_domain": meta["risk_domain"],
                "mechanism_tags": meta["mechanism_tags"],
                "level": chain.get("level"),
                "score": chain.get("score"),
                "confidence": chain.get("score"),
                "geometry": chain.get("region"),
                "dominant_factors": chain.get("dominant_evidence") or [],
                "linked_systems": chain.get("linked_systems") or [],
                "source_grid": meta["score_grid"],
                "source_chain_ids": [chain.get("id")],
            }
            if hazard_type == "severe_convection_composite" and "convection_potential" not in by_target:
                continue
            out.append(item)
    return out
```

Add `risk_diagnoses` to the returned result from `diagnose_nafp_situation`.

- [ ] **Step 5: Implement point conversion**

In `weather_diag/diagnosis/point.py`, add a local helper mirroring the area helper but without geometry:

```python
def point_risk_diagnoses_from_chains(evidence_chains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from weather_diag.diagnosis.risk_taxonomy import hazard_metadata, legacy_target_hazards

    out = []
    for chain in evidence_chains:
        for hazard_type in legacy_target_hazards(str(chain.get("target_type"))):
            meta = hazard_metadata(hazard_type)
            out.append({
                "risk_id": f"point-risk-{hazard_type}",
                "hazard_type": hazard_type,
                "label": meta["label"],
                "risk_domain": meta["risk_domain"],
                "mechanism_tags": meta["mechanism_tags"],
                "level": chain.get("level"),
                "score": chain.get("score"),
                "confidence": chain.get("score"),
                "dominant_factors": chain.get("dominant_evidence") or [],
                "source_grid": meta["score_grid"],
                "source_chain_ids": [chain.get("id")],
            })
    return out
```

Add `risk_diagnoses` to the returned result from `diagnose_nafp_point`.

- [ ] **Step 6: Verify NAFP and point tests**

Run:

```bash
python -m pytest tests/test_nafp_situation.py tests/test_nafp_point_diagnosis.py -q
```

Expected: all tests pass.

## Task 7: Serve NAFP Dynamic Risk Layers

**Files:**
- Modify: `weather_diag/diagnosis/nafp_layers.py`
- Modify: `configs/layers.yaml`
- Test: `tests/test_nafp_layers.py`

- [ ] **Step 1: Add failing NAFP layer test**

Append to `tests/test_nafp_layers.py`:

```python
def test_nafp_layers_include_multi_hazard_risk_scores():
    result = load_nafp_layer(
        root=NAFP_SAMPLE_ROOT,
        layer_id="risk_short_duration_heavy_rain_score",
        run_time="2026-06-17T20:00:00",
        forecast_hour=24,
    )

    assert result.layer_id == "risk_short_duration_heavy_rain_score"
    assert result.values.shape
    assert result.metadata["units"] == "0-1"
```

Use the existing helper names in `tests/test_nafp_layers.py`; if the file imports a different public function, use that existing function.

- [ ] **Step 2: Run failing NAFP layer test**

Run:

```bash
python -m pytest tests/test_nafp_layers.py::test_nafp_layers_include_multi_hazard_risk_scores -q
```

Expected: FAIL because the layer id is unknown.

- [ ] **Step 3: Add dynamic layer support**

In `weather_diag/diagnosis/nafp_layers.py`:

1. Import `multi_hazard_score_details`.
2. Reuse the existing `_risk_scores` field loading path.
3. Return the requested grid from `multi_hazard_score_details(... )["scores"]`.
4. Register these layer ids:

```python
"risk_persistent_heavy_rain_score"
"risk_short_duration_heavy_rain_score"
"risk_thunderstorm_gale_score"
"risk_hail_score"
"risk_rotating_storm_score"
"risk_severe_convection_composite_score"
"risk_precipitation_composite_score"
```

- [ ] **Step 4: Verify NAFP layer tests**

Run:

```bash
python -m pytest tests/test_nafp_layers.py -q
```

Expected: all NAFP layer tests pass.

## Task 8: Update Conclusions To Prefer Hazard Types

**Files:**
- Modify: `weather_diag/diagnosis/conclusions.py`
- Modify: `weather_diag/analysis/report.py`
- Test: `tests/test_diagnosis_conclusions.py`

- [ ] **Step 1: Add failing conclusion test**

Append to `tests/test_diagnosis_conclusions.py`:

```python
def test_conclusions_from_features_uses_hazard_type_labels():
    conclusions = conclusions_from_features([
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
                "dominant_factors": [{"label": "水汽辐合", "mean_contribution": 0.20}],
                "supporting_systems": [{"type": "low_level_convergence", "relation": "overlap"}],
            },
        }
    ])

    assert conclusions[0]["hazard_type"] == "short_duration_heavy_rain"
    assert "短时强降水" in conclusions[0]["headline"]
    assert conclusions[0]["risk_domain"] == ["precipitation", "severe_convection"]
```

- [ ] **Step 2: Run failing conclusion test**

Run:

```bash
python -m pytest tests/test_diagnosis_conclusions.py::test_conclusions_from_features_uses_hazard_type_labels -q
```

Expected: FAIL because the current conclusion generator only knows old target types.

- [ ] **Step 3: Update labels and output shape**

In `weather_diag/diagnosis/conclusions.py`:

1. Import taxonomy helpers.
2. In `conclusions_from_features`, read `hazard_type = props.get("hazard_type")`.
3. If `hazard_type` is present, use taxonomy label and include:

```python
"hazard_type": hazard_type,
"risk_domain": props.get("risk_domain") or [],
"source_grid": props.get("source_grid"),
```

4. Keep old behavior for `heavy_rain_risk` and `convection_risk`.

- [ ] **Step 4: Verify conclusion tests**

Run:

```bash
python -m pytest tests/test_diagnosis_conclusions.py -q
```

Expected: all conclusion tests pass.

## Task 9: Update API Documentation And Algorithm Catalog

**Files:**
- Modify: `weather_diag/diagnosis/algorithm_rules.py`
- Modify: `docs/api.md`
- Modify: `docs/algorithms.md`
- Test: `tests/test_algorithm_management.py`

- [ ] **Step 1: Add algorithm catalog assertions**

In `tests/test_algorithm_management.py`, add or extend a test to assert:

```python
    chain_targets = {
        chain["target"]
        for item in catalog
        if item["algorithm_id"] == "nafp-situation"
        for chain in item["evidence_chains"]
    }
    assert "short_duration_heavy_rain" in chain_targets
    assert "thunderstorm_gale" in chain_targets
    assert "hail" in chain_targets
    assert "rotating_storm_or_supercell" in chain_targets
```

- [ ] **Step 2: Run failing catalog test**

Run:

```bash
python -m pytest tests/test_algorithm_management.py -q
```

Expected: FAIL because the catalog does not expose new hazard targets.

- [ ] **Step 3: Update `ALGORITHM_CATALOG`**

In `weather_diag/diagnosis/algorithm_rules.py`, add evidence-chain catalog entries:

```python
{"chain_id": "persistent_heavy_rain", "name": "持续性强降水", "target": "persistent_heavy_rain", "method": "水汽输送、水汽辐合、上升运动和累计降水综合评分"}
{"chain_id": "short_duration_heavy_rain", "name": "短时强降水", "target": "short_duration_heavy_rain", "method": "低层水汽、CAPE/K指数、低层触发和水汽辐合综合评分"}
{"chain_id": "thunderstorm_gale", "name": "雷暴大风", "target": "thunderstorm_gale", "method": "DCAPE、深层风切变、CAPE和低层触发综合评分"}
{"chain_id": "hail", "name": "冰雹", "target": "hail", "method": "CAPE、深层风切变和冷性层结代理指标综合评分"}
{"chain_id": "rotating_storm_or_supercell", "name": "旋转风暴/超级单体潜势", "target": "rotating_storm_or_supercell", "method": "CAPE、深层风切变、低层切变或SRH综合评分"}
```

Keep existing `heavy_rain_potential` and `convection_potential`.

- [ ] **Step 4: Update docs**

In `docs/api.md`, document:

```markdown
`risk_diagnoses` is the canonical multi-hazard risk conclusion list. Legacy
`evidence_chains` and `diagnosis_conclusions` remain available.
```

In `docs/algorithms.md`, add the grid list and rule that each hazard is a separate continuous score field.

- [ ] **Step 5: Verify algorithm management tests**

Run:

```bash
python -m pytest tests/test_algorithm_management.py -q
```

Expected: all algorithm management tests pass.

## Task 10: Update Frontend Risk Grouping And Layer Recommendations

**Files:**
- Modify: `frontend/map.js`
- Modify: `frontend/maplibre-utils.js`
- Test: `tests/frontend-maplibre-utils.test.js`
- Test: `tests/frontend-map-point-diagnosis.test.js`

- [ ] **Step 1: Add frontend utility test**

In `tests/frontend-maplibre-utils.test.js`, add:

```javascript
test('recommended layer supports multi-hazard risk features', () => {
  const available = [
    'risk_short_duration_heavy_rain_score',
    'risk_thunderstorm_gale_score',
    'risk_hail_score'
  ];
  assert.deepEqual(
    recommendedFeatureLayer({ feature_type: 'short_duration_heavy_rain_risk' }, available),
    { layerId: 'risk_short_duration_heavy_rain_score', reason: 'risk-score' }
  );
  assert.deepEqual(
    recommendedFeatureLayer({ feature_type: 'hail_risk' }, available),
    { layerId: 'risk_hail_score', reason: 'risk-score' }
  );
});
```

- [ ] **Step 2: Run failing frontend utility test**

Run:

```bash
node --test tests/frontend-maplibre-utils.test.js
```

Expected: FAIL because recommendations are absent.

- [ ] **Step 3: Update `FEATURE_LAYER_RECOMMENDATIONS`**

In `frontend/maplibre-utils.js`, add:

```javascript
persistent_heavy_rain_risk: { candidates: ['risk_persistent_heavy_rain_score', 'risk_precipitation_composite_score'], reason: 'risk-score' },
short_duration_heavy_rain_risk: { candidates: ['risk_short_duration_heavy_rain_score', 'risk_precipitation_composite_score'], reason: 'risk-score' },
thunderstorm_gale_risk: { candidates: ['risk_thunderstorm_gale_score', 'risk_severe_convection_composite_score'], reason: 'risk-score' },
hail_risk: { candidates: ['risk_hail_score', 'risk_severe_convection_composite_score'], reason: 'risk-score' },
rotating_storm_risk: { candidates: ['risk_rotating_storm_score', 'risk_severe_convection_composite_score'], reason: 'risk-score' },
severe_convection_composite_risk: { candidates: ['risk_severe_convection_composite_score'], reason: 'risk-score' },
```

- [ ] **Step 4: Update map labels**

In `frontend/map.js`, add to `featureTypes`, `featureColors`, and `pointTargetNames`:

```javascript
['persistent_heavy_rain_risk', '持续性强降水']
['short_duration_heavy_rain_risk', '短时强降水']
['thunderstorm_gale_risk', '雷暴大风']
['hail_risk', '冰雹']
['rotating_storm_risk', '旋转风暴/超级单体潜势']
['severe_convection_composite_risk', '强对流综合风险']
```

For point diagnosis, render `result.risk_diagnoses` above raw evidence chains when present. Keep `result.scores` fallback.

- [ ] **Step 5: Verify frontend tests**

Run:

```bash
node --test tests/frontend-maplibre-utils.test.js tests/frontend-map-point-diagnosis.test.js
```

Expected: all frontend tests pass.

## Task 11: Regenerate Demo Products And Smoke Test API

**Files:**
- Modify generated: `data/products/ecmwf_demo/**`
- Test: generated product contract

- [ ] **Step 1: Regenerate demo data and products**

Run:

```bash
python scripts/generate_demo_data.py --output data/raw/ecmwf_demo.nc
python -c "from weather_diag.pipeline import diagnose_file; diagnose_file('data/raw/ecmwf_demo.nc', model='ecmwf', run_id='ecmwf_demo')"
```

Expected: command exits 0 and `data/products/ecmwf_demo/fh_024/diagnostics.nc` contains the new risk variables.

- [ ] **Step 2: Smoke test local API with proxy bypass**

If the app is running:

```bash
curl --noproxy '*' -fsS 'http://127.0.0.1:8000/api/layers/risk_short_duration_heavy_rain_score/metadata?run_id=ecmwf_demo&forecast_hour=24'
curl --noproxy '*' -fsS 'http://127.0.0.1:8000/api/features?run_id=ecmwf_demo&forecast_hour=24&type=short_duration_heavy_rain_risk'
```

Expected: both requests return JSON and the feature response contains a `FeatureCollection`.

- [ ] **Step 3: Run full verification**

Run:

```bash
python -m pytest tests/test_risk_taxonomy.py tests/test_risk_features.py tests/test_diagnosis_conclusions.py tests/test_system_links.py tests/test_nafp_situation.py tests/test_nafp_point_diagnosis.py tests/test_nafp_layers.py tests/test_algorithm_management.py -q
node --test tests/frontend-maplibre-utils.test.js tests/frontend-map-point-diagnosis.test.js
```

Expected: all selected Python and Node tests pass.

## Rollback

Rollback is file-based and low risk because no external data store is introduced.

To rollback:

```bash
git revert <commits-from-this-plan>
python scripts/generate_demo_data.py --output data/raw/ecmwf_demo.nc
python -c "from weather_diag.pipeline import diagnose_file; diagnose_file('data/raw/ecmwf_demo.nc', model='ecmwf', run_id='ecmwf_demo')"
```

Expected: old `heavy_rain_score`, `convection_score`, `heavy_rain_risk`, and `convection_risk` remain available because the plan keeps them through the migration.

## Self-Review

- Spec coverage: covered multiple risk grids, multi-label short-duration heavy rain, risk objects, weather-system support links, NAFP area and point diagnosis, frontend grouped display, docs, and generated products.
- Placeholder scan: no deferred implementation placeholders are required for Phase 1.
- Type consistency: use `hazard_type`, `risk_domain`, `mechanism_tags`, `source_grid`, `source_chain_ids`, and `risk_diagnoses` consistently across tasks.
- Risk: Task 6 maps NAFP area/point risk diagnoses from broad legacy chains at first; product pipeline grids become more granular immediately. A later calibration pass can refine NAFP per-hazard scoring, but the public contract will already be stable.
