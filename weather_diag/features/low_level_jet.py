from __future__ import annotations

import numpy as np

from weather_diag.features.transport_objects import ranked_transport_components
from weather_diag.io.geojson import line_feature


def detect_low_level_jet(
    wind850_speed: np.ndarray,
    moisture_flux850: np.ndarray | None,
    lat,
    lon,
    thresholds: dict,
    *,
    u850: np.ndarray | None = None,
    v850: np.ndarray | None = None,
) -> list[dict]:
    cfg = thresholds.get("low_level_jet", {})
    ws_min = float(cfg.get("wind_speed_min_ms", 12.0))
    min_pts = int(cfg.get("min_area_grid_points", 10))
    max_objects = int(cfg.get("max_objects", 12))
    min_coherence = float(cfg.get("min_direction_coherence", 0.65))
    mask = np.asarray(wind850_speed) >= ws_min
    flux_threshold = None
    if moisture_flux850 is not None:
        p = float(cfg.get("moisture_flux_percentile", 70))
        flux_threshold = float(np.nanpercentile(moisture_flux850, p))
        mask &= moisture_flux850 >= flux_threshold
    components = ranked_transport_components(
        mask,
        lat,
        lon,
        wind850_speed,
        min_points=min_pts,
        max_objects=max_objects,
        u=u850,
        v=v850,
        min_direction_coherence=min_coherence if u850 is not None and v850 is not None else 0.0,
        length_cap_km=float(cfg.get("rank_length_cap_km", 1800.0)),
        mean_weight=float(cfg.get("rank_mean_weight", 0.35)),
        max_weight=float(cfg.get("rank_max_weight", 0.30)),
        length_weight=float(cfg.get("rank_length_weight", 0.20)),
        coherence_weight=float(cfg.get("rank_coherence_weight", 0.15)),
        streamline_max_turn_deg=float(cfg.get("streamline_max_turn_deg", 55.0)),
        streamline_allow_gap_grid=int(cfg.get("streamline_allow_gap_grid", 1)),
    )

    features = []
    for component in components:
        max_ws = component["max_value"]
        props = {
            "id": f"low_level_jet_{component['rank']:03d}",
            "feature_type": "low_level_jet",
            "title": "850hPa 低空急流轴",
            "level": "850hPa",
            "rank": component["rank"],
            "point_count": component["point_count"],
            "axis_length": component["axis_length"],
            "axis_length_km": round(component.get("axis_length_km", 0.0), 1),
            "rank_score": component.get("rank_score"),
            "length_score_capped_km": component.get("length_score_capped_km"),
            "axis_method": component.get("axis_method"),
            "max_wind_ms": round(max_ws, 2),
            "mean_wind_ms": round(component["mean_value"], 2),
            "direction_coherence": None if component["direction_coherence"] is None else round(component["direction_coherence"], 3),
            "confidence": round(min(0.92, 0.58 + (max_ws - ws_min) / max(ws_min, 1) * 0.22), 2),
            "evidence": [
                f"850hPa 风速达到 {max_ws:.1f} m/s",
                "风速高值呈连续轴带分布",
                "风矢量流线追踪得到低空急流轴" if component.get("axis_method") == "streamline_axis" else "风速高值区几何主轴作为低空急流轴",
                "按强度、长度封顶和风向一致性综合排序，避免长而弱的轴线优先",
                "风向一致性满足低空急流轴判断" if component["direction_coherence"] is not None else "未提供风矢量一致性检验",
            ],
        }
        if flux_threshold is not None:
            props["moisture_flux_threshold"] = flux_threshold
            props["evidence"].append("低空急流轴与水汽通量高值重叠")
        features.append(line_feature(component["line"]["coordinates"], props))
    return features
