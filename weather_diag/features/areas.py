from __future__ import annotations

import numpy as np
from weather_diag.diagnostics.grid import mask_to_bbox_features
from weather_diag.io.geojson import polygon_feature


def mask_area_features(mask, lat, lon, *, feature_type: str, title: str, value_field: np.ndarray | None = None,
                       threshold_desc: str = "", min_points: int = 10, evidence: list[str] | None = None,
                       extra_props: dict | None = None):
    out = []
    for i, item in enumerate(mask_to_bbox_features(mask, lat, lon, min_points=min_points), start=1):
        ys, xs = item["indices"]
        max_value = None
        mean_value = None
        if value_field is not None:
            vals = value_field[ys, xs]
            max_value = float(np.nanmax(vals)) if vals.size else None
            mean_value = float(np.nanmean(vals)) if vals.size else None
        props = {
            "id": f"{feature_type}_{i:03d}",
            "feature_type": feature_type,
            "title": title,
            "confidence": 0.65,
            "point_count": item["point_count"],
            "centroid": item["centroid"],
            "bbox": item["bbox"],
            "max_value": max_value,
            "mean_value": mean_value,
            "evidence": evidence or [threshold_desc or "满足阈值条件的连通区域"],
        }
        if extra_props:
            props.update(extra_props)
        out.append(polygon_feature(item["geometry"], props))
    return out
