from __future__ import annotations

import numpy as np
from scipy import ndimage

from weather_diag.io.geojson import point_feature


def _local_extrema(field: np.ndarray, mode: str, size: int):
    arr = np.asarray(field, dtype=float)
    if mode == "max":
        filt = ndimage.maximum_filter(arr, size=size, mode="nearest")
        return np.where((arr == filt) & np.isfinite(arr))
    filt = ndimage.minimum_filter(arr, size=size, mode="nearest")
    return np.where((arr == filt) & np.isfinite(arr))


def detect_high_low(mslp: np.ndarray, lat: np.ndarray, lon: np.ndarray, thresholds: dict) -> list[dict]:
    cfg = thresholds.get("pressure_system", {})
    size = int(cfg.get("min_distance_grid", 6))
    max_centers = int(cfg.get("max_centers", 20))
    prominence = float(cfg.get("min_prominence_hpa", 1.5))
    features = []
    arr = np.asarray(mslp, dtype=float)

    for mode, ftype, label in [("max", "high", "H"), ("min", "low", "L")]:
        ys, xs = _local_extrema(arr, mode, size=size)
        candidates = []
        for y, x in zip(ys, xs):
            y0, y1 = max(0, y-size), min(arr.shape[0], y+size+1)
            x0, x1 = max(0, x-size), min(arr.shape[1], x+size+1)
            local = arr[y0:y1, x0:x1]
            val = arr[y, x]
            if mode == "max":
                prom = val - np.nanmean(local)
            else:
                prom = np.nanmean(local) - val
            if prom >= prominence:
                candidates.append((prom, y, x, val))
        candidates.sort(reverse=True, key=lambda item: item[0])
        for prom, y, x, val in candidates[:max_centers]:
            confidence = float(min(0.98, 0.45 + prom / max(1.0, prominence) * 0.12))
            props = {
                "id": f"{ftype}_{len(features)+1:03d}",
                "feature_type": ftype,
                "label": label,
                "level": "mslp",
                "value": round(float(val), 2),
                "unit": "hPa",
                "confidence": round(confidence, 2),
                "evidence": [
                    "局地气压极值明显",
                    f"中心值相对周边差异约 {prom:.1f} hPa",
                    "MVP 使用局地极值和相对差异识别，后续可加入闭合等压线判定",
                ],
            }
            features.append(point_feature(float(lon[x]), float(lat[y]), props))
    return features
