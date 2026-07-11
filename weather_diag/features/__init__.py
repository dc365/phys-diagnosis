from __future__ import annotations

import numpy as np

# Sounding analysis enables ``enable_meridional_valley_tracks`` in its
# trough/ridge thresholds. Use that existing opt-in as the compatibility gate
# for the contour-seeded detector, while leaving model-grid/NAFP detection on the
# established trough_ridge implementation.
from . import trough_ridge as _trough_ridge


if not getattr(_trough_ridge.detect_trough_ridge, "_contour_seeded_wrapper", False):
    _original_detect_trough_ridge = _trough_ridge.detect_trough_ridge

    def _effective_thresholds(thresholds: dict | None) -> dict | None:
        if not thresholds:
            return thresholds
        if "trough_ridge" in thresholds:
            output = dict(thresholds)
            raw = dict(thresholds.get("trough_ridge") or {})
            output["trough_ridge"] = raw
        else:
            raw = dict(thresholds)
            output = raw

        if not raw.get("enable_meridional_valley_tracks", False):
            return output

        # Sounding-only extension.  The previous 95-120E recovery corridor could
        # not see the Mongolia/western-Russia or eastern-Russia height valleys.
        # Keep the tracker automatic, but widen its search domain and allow a few
        # independent north-south tracks. Model-grid paths do not enable this gate.
        raw["meridional_track_lon_min"] = min(
            float(raw.get("meridional_track_lon_min", 95.0)),
            88.0,
        )
        raw["meridional_track_lon_max"] = max(
            float(raw.get("meridional_track_lon_max", 120.0)),
            136.0,
        )
        raw["meridional_track_lat_min"] = min(
            float(raw.get("meridional_track_lat_min", 15.0)),
            15.0,
        )
        raw["meridional_track_lat_max"] = max(
            float(raw.get("meridional_track_lat_max", 52.0)),
            55.0,
        )
        raw["meridional_track_max_lines"] = max(
            int(raw.get("meridional_track_max_lines", 2)),
            4,
        )
        raw.setdefault("meridional_track_min_depth_gpm", 0.45)
        raw.setdefault("meridional_track_min_mean_depth_gpm", 0.65)
        raw.setdefault("meridional_track_min_peak_depth_gpm", 1.2)
        raw.setdefault("meridional_track_max_lon_step_deg", 2.8)
        return output

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

    def _coordinates(feature: dict) -> np.ndarray:
        values = np.asarray(
            (feature.get("geometry") or {}).get("coordinates") or [],
            dtype=float,
        )
        if values.ndim != 2 or values.shape[0] < 2 or values.shape[1] < 2:
            return np.empty((0, 2), dtype=float)
        return values[:, :2]

    def _line_intersects(
        feature: dict,
        bounds: tuple[float, float, float, float],
    ) -> bool:
        lon_min, lat_min, lon_max, lat_max = bounds
        coordinates = _coordinates(feature)
        if coordinates.size == 0:
            return False
        return bool(
            np.any(
                (coordinates[:, 0] >= lon_min)
                & (coordinates[:, 0] <= lon_max)
                & (coordinates[:, 1] >= lat_min)
                & (coordinates[:, 1] <= lat_max)
            )
        )

    def _is_meridional_track(feature: dict) -> bool:
        props = feature.get("properties") or {}
        if props.get("candidate_source") != "meridional_valley_track":
            return False
        coordinates = _coordinates(feature)
        if coordinates.size == 0:
            return False
        lon_span = float(np.ptp(coordinates[:, 0]))
        lat_span = float(np.ptp(coordinates[:, 1]))
        return lat_span >= 4.0 and lon_span <= 1.7 * max(lat_span, 0.5)

    def _is_duplicate(feature: dict, existing: list[dict]) -> bool:
        coordinates = _coordinates(feature)
        if coordinates.size == 0:
            return True
        for item in existing:
            old = _coordinates(item)
            if old.size == 0:
                continue
            if _trough_ridge._polyline_mean_distance_km(coordinates, old) < 240.0:
                return True
        return False

    def _merge_meridional_fallbacks(
        contour_troughs: list[dict],
        original_troughs: list[dict],
    ) -> list[dict]:
        """Merge only independent valley tracks, never broad score components.

        The broad legacy components caused the unwanted Northeast diagonal bridge.
        The one-dimensional valley tracker is safer: it follows a local height
        minimum at each latitude and therefore can supply missing Mongolia/Russia
        axes without joining nearby systems into one PCA curve.
        """

        if not contour_troughs:
            return original_troughs

        output = list(contour_troughs)
        southern_bounds = (104.0, 13.0, 115.0, 26.0)
        has_southern = any(
            _line_intersects(feature, southern_bounds)
            for feature in output
        )
        added = 0
        for feature in original_troughs:
            if not _is_meridional_track(feature):
                continue
            if _is_duplicate(feature, output):
                continue
            is_southern = _line_intersects(feature, (95.0, 15.0, 120.0, 32.0))
            if is_southern and has_southern:
                continue
            output.append(feature)
            added += 1
            has_southern = has_southern or is_southern
            if added >= 3:
                break
        return output

    def _detect_trough_ridge_with_contour_seeds(
        z500,
        lat,
        lon,
        thresholds=None,
        vorticity500=None,
    ):
        effective = _effective_thresholds(thresholds)
        original_troughs, ridges = _original_detect_trough_ridge(
            z500,
            lat,
            lon,
            effective,
            vorticity500=vorticity500,
        )
        raw = (effective or {}).get("trough_ridge", effective or {})
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
        return _merge_meridional_fallbacks(contour_troughs, original_troughs), ridges

    _detect_trough_ridge_with_contour_seeds._contour_seeded_wrapper = True
    _trough_ridge.detect_trough_ridge = _detect_trough_ridge_with_contour_seeds
