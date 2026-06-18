from __future__ import annotations

import numpy as np
from scipy.signal import argrelextrema
from weather_diag.io.geojson import line_feature


def _candidate_lines_from_anomaly(anom: np.ndarray, lat, lon, *, mode: str, percentile: float, min_points: int, max_lines: int):
    # MVP heuristic: at each latitude, find strongest negative/positive anomaly along longitude,
    # then group contiguous latitudes into candidate meridional axes.
    pts = []
    for yi in range(anom.shape[0]):
        row = anom[yi]
        if not np.isfinite(row).any():
            continue
        if mode == "trough":
            val = np.nanmin(row)
            threshold = np.nanpercentile(anom, percentile)
            if val <= threshold:
                xi = int(np.nanargmin(row)); pts.append((yi, xi, float(val)))
        else:
            val = np.nanmax(row)
            threshold = np.nanpercentile(anom, 100 - percentile)
            if val >= threshold:
                xi = int(np.nanargmax(row)); pts.append((yi, xi, float(val)))
    if not pts:
        return []
    # Split if longitude jumps too much.
    groups = []
    current = [pts[0]]
    for p in pts[1:]:
        if abs(p[1] - current[-1][1]) <= 8:
            current.append(p)
        else:
            groups.append(current); current = [p]
    groups.append(current)
    groups = [g for g in groups if len(g) >= min_points]
    groups.sort(key=len, reverse=True)
    features = []
    for i, g in enumerate(groups[:max_lines], start=1):
        coords = [[float(lon[x]), float(lat[y])] for y, x, _ in g]
        feature_type = "trough" if mode == "trough" else "ridge"
        title = "500hPa 槽线候选" if mode == "trough" else "500hPa 脊线候选"
        evidence = [
            "基于 500hPa 位势高度距平轴线的启发式识别",
            "MVP 阶段为候选线，需结合等高线形态、涡度和人工订正",
        ]
        features.append(line_feature(coords, {
            "id": f"{feature_type}_{i:03d}", "feature_type": feature_type, "title": title,
            "level": "500hPa", "confidence": 0.55, "evidence": evidence,
        }))
    return features


def detect_trough_ridge(z500: np.ndarray, lat, lon, thresholds: dict) -> tuple[list[dict], list[dict]]:
    cfg = thresholds.get("trough_ridge", {})
    percentile = float(cfg.get("anomaly_percentile", 20))
    min_points = int(cfg.get("min_points_per_line", 4))
    max_lines = int(cfg.get("max_lines", 8))
    # Remove meridional mean to get synoptic anomaly.
    anom = z500 - np.nanmean(z500, axis=1, keepdims=True)
    troughs = _candidate_lines_from_anomaly(anom, lat, lon, mode="trough", percentile=percentile, min_points=min_points, max_lines=max_lines)
    ridges = _candidate_lines_from_anomaly(anom, lat, lon, mode="ridge", percentile=percentile, min_points=min_points, max_lines=max_lines)
    return troughs, ridges
