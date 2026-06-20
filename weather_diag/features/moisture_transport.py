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
                    "max_value": component["max_value"],
                    "mean_value": component["mean_value"],
                    "flux_threshold": threshold,
                    "direction_coherence": None if component["direction_coherence"] is None else round(component["direction_coherence"], 3),
                    "confidence": 0.72 if component["direction_coherence"] is not None else 0.66,
                    "evidence": [
                        f"850hPa 水汽通量超过第 {p:.0f} 百分位阈值",
                        "水汽通量高值呈连续输送带",
                        "风向一致性支持水汽沿轴向输送" if component["direction_coherence"] is not None else "未提供风矢量一致性检验",
                    ],
                },
            )
        )
    return features
