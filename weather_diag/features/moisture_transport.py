from __future__ import annotations

import numpy as np

from weather_diag.features.transport_objects import ranked_transport_components
from weather_diag.io.geojson import line_feature


def detect_moisture_transport(
    moisture_flux850: np.ndarray,
    lat,
    lon,
    thresholds: dict,
    *,
    u850: np.ndarray | None = None,
    v850: np.ndarray | None = None,
) -> list[dict]:
    cfg = thresholds.get("moisture_transport", {})
    p = float(cfg.get("flux_percentile", 75))
    min_pts = int(cfg.get("min_area_grid_points", 12))
    max_objects = int(cfg.get("max_objects", 12))
    min_coherence = float(cfg.get("min_direction_coherence", 0.65))
    threshold = float(np.nanpercentile(moisture_flux850, p))
    mask = np.asarray(moisture_flux850) >= threshold
    components = ranked_transport_components(
        mask,
        lat,
        lon,
        moisture_flux850,
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
        features.append(
            line_feature(
                component["line"]["coordinates"],
                {
                    "id": f"moisture_transport_{component['rank']:03d}",
                    "feature_type": "moisture_transport",
                    "title": "850hPa 水汽输送带",
                    "level": "850hPa",
                    "rank": component["rank"],
                    "point_count": component["point_count"],
                    "axis_length": component["axis_length"],
                    "axis_length_km": round(component.get("axis_length_km", 0.0), 1),
                    "rank_score": component.get("rank_score"),
                    "length_score_capped_km": component.get("length_score_capped_km"),
                    "axis_method": component.get("axis_method"),
                    "max_value": component["max_value"],
                    "mean_value": component["mean_value"],
                    "flux_threshold": threshold,
                    "direction_coherence": None if component["direction_coherence"] is None else round(component["direction_coherence"], 3),
                    "confidence": 0.72 if component["direction_coherence"] is not None else 0.66,
                    "evidence": [
                        f"850hPa 水汽通量超过第 {p:.0f} 百分位阈值",
                        "水汽通量高值呈连续输送带",
                        "风矢量流线追踪得到输送轴" if component.get("axis_method") == "streamline_axis" else "高值区几何主轴作为输送轴",
                        "按强度、长度封顶和风向一致性综合排序，避免长而弱的输送带优先",
                        "风向一致性支持水汽沿轴向输送" if component["direction_coherence"] is not None else "未提供风矢量一致性检验",
                    ],
                },
            )
        )
    return features
