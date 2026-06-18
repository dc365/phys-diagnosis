from __future__ import annotations

import numpy as np
from weather_diag.diagnostics.grid import mask_to_bbox_features
from weather_diag.io.geojson import line_feature, polygon_feature


def detect_low_level_jet(wind850_speed: np.ndarray, moisture_flux850: np.ndarray | None, lat, lon, thresholds: dict) -> list[dict]:
    cfg = thresholds.get("low_level_jet", {})
    ws_min = float(cfg.get("wind_speed_min_ms", 12.0))
    min_pts = int(cfg.get("min_area_grid_points", 10))
    mask = np.asarray(wind850_speed) >= ws_min
    if moisture_flux850 is not None:
        p = float(cfg.get("moisture_flux_percentile", 70))
        mf_thr = np.nanpercentile(moisture_flux850, p)
        mask = mask & (moisture_flux850 >= mf_thr)
    features = []
    for i, item in enumerate(mask_to_bbox_features(mask, lat, lon, min_points=min_pts), start=1):
        ys, xs = item["indices"]
        max_ws = float(np.nanmax(wind850_speed[ys, xs]))
        lat_c = float(np.nanmean(lat[ys]))
        lon_min, lon_max = float(np.nanmin(lon[xs])), float(np.nanmax(lon[xs]))
        coords = [[lon_min, lat_c], [lon_max, lat_c]]
        props = {
            "id": f"low_level_jet_{i:03d}",
            "feature_type": "low_level_jet",
            "title": "850hPa 低空急流轴候选",
            "level": "850hPa",
            "max_wind_ms": round(max_ws, 2),
            "confidence": round(min(0.92, 0.55 + (max_ws - ws_min) / max(ws_min, 1) * 0.25), 2),
            "evidence": [
                f"850hPa 风速达到 {max_ws:.1f} m/s",
                "风速高值呈连通带状分布",
                "若与水汽通量高值重叠，可作为暴雨水汽输送通道候选",
            ],
        }
        features.append(line_feature(coords, props))
    return features
