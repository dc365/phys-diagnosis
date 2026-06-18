from __future__ import annotations

import numpy as np
from weather_diag.diagnostics.grid import mask_to_bbox_features
from weather_diag.io.geojson import line_feature


def detect_moisture_transport(moisture_flux850: np.ndarray, lat, lon, thresholds: dict) -> list[dict]:
    cfg = thresholds.get("moisture_transport", {})
    p = float(cfg.get("flux_percentile", 75))
    min_pts = int(cfg.get("min_area_grid_points", 12))
    thr = float(np.nanpercentile(moisture_flux850, p))
    mask = np.asarray(moisture_flux850) >= thr
    features = []
    for i, item in enumerate(mask_to_bbox_features(mask, lat, lon, min_points=min_pts), start=1):
        ys, xs = item["indices"]
        max_val = float(np.nanmax(moisture_flux850[ys, xs]))
        lat_c = float(np.nanmean(lat[ys]))
        coords = [[float(np.nanmin(lon[xs])), lat_c], [float(np.nanmax(lon[xs])), lat_c]]
        features.append(line_feature(coords, {
            "id": f"moisture_transport_{i:03d}",
            "feature_type": "moisture_transport",
            "title": "850hPa 水汽输送带候选",
            "level": "850hPa",
            "max_value": max_val,
            "confidence": 0.68,
            "evidence": [
                f"850hPa 水汽通量超过第 {p:.0f} 百分位阈值",
                "该带状区域可作为暖湿水汽输送通道候选",
            ],
        }))
    return features
