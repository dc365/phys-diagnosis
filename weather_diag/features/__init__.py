from __future__ import annotations

# Sounding analysis enables ``enable_meridional_valley_tracks`` in its
# trough/ridge thresholds. Use that existing opt-in as the compatibility gate
# for the contour-seeded detector, while leaving model-grid/NAFP detection on the
# established trough_ridge implementation.
from . import trough_ridge as _trough_ridge


if not getattr(_trough_ridge.detect_trough_ridge, "_contour_seeded_wrapper", False):
    _original_detect_trough_ridge = _trough_ridge.detect_trough_ridge

    def _contour_thresholds(raw: dict) -> dict:
        mapping = {
            "analysis_lat_min": raw.get("analysis_lat_min", 13.0),
            "analysis_lat_max": raw.get("analysis_lat_max", 55.0),
            "analysis_lon_min": raw.get("analysis_lon_min", 60.0),
            "analysis_lon_max": raw.get("analysis_lon_max", 150.0),
            "smooth_radius_km": raw.get("smooth_radius_km", 150.0),
            "min_length_km": raw.get("min_length_km", 320.0),
            "max_lines": raw.get("max_lines", 8),
            "output_points": raw.get("output_points", 28),
            "trace_min_lat_span_deg": raw.get(
                "meridional_track_min_lat_span_deg",
                4.0,
            ),
            "low_lat_zonal_filter_max_lat": raw.get(
                "low_lat_zonal_filter_max_lat",
                30.0,
            ),
            "low_lat_zonal_max_aspect_ratio": raw.get(
                "low_lat_zonal_max_aspect_ratio",
                1.5,
            ),
        }
        return {"contour_trough": mapping}

    def _line_intersects(feature: dict, bounds: tuple[float, float, float, float]) -> bool:
        lon_min, lat_min, lon_max, lat_max = bounds
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        return any(
            len(point) >= 2
            and lon_min <= float(point[0]) <= lon_max
            and lat_min <= float(point[1]) <= lat_max
            for point in coordinates
        )

    def _merge_southern_fallback(
        contour_troughs: list[dict],
        original_troughs: list[dict],
    ) -> list[dict]:
        """Keep one legacy weak southern track only when contours miss it.

        The original synoptic-score components are intentionally not merged after
        contour seeds succeed, because those broad components caused the unwanted
        Northeast diagonal bridge. The legacy meridional recovery remains a safe
        fallback for sparse low-latitude observations.
        """

        if not contour_troughs:
            return original_troughs
        southern_bounds = (104.0, 13.0, 115.0, 26.0)
        if any(_line_intersects(feature, southern_bounds) for feature in contour_troughs):
            return contour_troughs
        for feature in original_troughs:
            props = feature.get("properties") or {}
            if props.get("candidate_source") != "meridional_valley_track":
                continue
            if _line_intersects(feature, (95.0, 15.0, 120.0, 32.0)):
                return [*contour_troughs, feature]
        return contour_troughs

    def _detect_trough_ridge_with_contour_seeds(
        z500,
        lat,
        lon,
        thresholds=None,
        vorticity500=None,
    ):
        original_troughs, ridges = _original_detect_trough_ridge(
            z500,
            lat,
            lon,
            thresholds,
            vorticity500=vorticity500,
        )
        raw = (thresholds or {}).get("trough_ridge", thresholds or {})
        enabled = bool(raw.get("enable_meridional_valley_tracks", False)) and bool(
            raw.get("enable_contour_seeded_troughs", True)
        )
        if not enabled:
            return original_troughs, ridges

        try:
            # Lazy import avoids loading Matplotlib for model/NAFP feature paths.
            from .contour_trough import detect_contour_seeded_troughs

            contour_troughs = detect_contour_seeded_troughs(
                z500,
                lat,
                lon,
                _contour_thresholds(raw),
                vorticity500=vorticity500,
            )
        except Exception:
            # Operational fallback: a contour extraction failure must not remove
            # the established height-trough product.
            return original_troughs, ridges
        return _merge_southern_fallback(contour_troughs, original_troughs), ridges

    _detect_trough_ridge_with_contour_seeds._contour_seeded_wrapper = True
    _trough_ridge.detect_trough_ridge = _detect_trough_ridge_with_contour_seeds
