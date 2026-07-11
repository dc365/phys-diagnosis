from __future__ import annotations

import numpy as np

# Sounding analysis enables ``enable_meridional_valley_tracks`` in its
# trough/ridge thresholds. Use that existing opt-in as the compatibility gate
# for the contour-seeded detector, while leaving model-grid/NAFP detection on the
# established trough_ridge implementation.
from . import trough_ridge as _trough_ridge


if not getattr(_trough_ridge.detect_trough_ridge, "_contour_seeded_wrapper", False):
    _original_detect_trough_ridge = _trough_ridge.detect_trough_ridge

    def _copy_thresholds(thresholds: dict | None) -> dict | None:
        if not thresholds:
            return thresholds
        if "trough_ridge" in thresholds:
            output = dict(thresholds)
            output["trough_ridge"] = dict(thresholds.get("trough_ridge") or {})
            return output
        return dict(thresholds)

    def _raw_thresholds(thresholds: dict | None) -> dict:
        return (thresholds or {}).get("trough_ridge", thresholds or {})

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

    def _is_duplicate(feature: dict, existing: list[dict], distance_km: float = 220.0) -> bool:
        coordinates = _coordinates(feature)
        if coordinates.size == 0:
            return True
        for item in existing:
            old = _coordinates(item)
            if old.size == 0:
                continue
            if _trough_ridge._polyline_mean_distance_km(coordinates, old) < distance_km:
                return True
        return False

    def _regional_thresholds(
        thresholds: dict | None,
        *,
        lon_min: float,
        lon_max: float,
        lat_min: float,
        lat_max: float,
        max_lines: int,
        min_length_km: float,
        min_depth_gpm: float,
        min_mean_depth_gpm: float,
        min_peak_depth_gpm: float,
    ) -> dict:
        output = _copy_thresholds(thresholds) or {"trough_ridge": {}}
        if "trough_ridge" not in output:
            output = {"trough_ridge": dict(output)}
        raw = output["trough_ridge"]
        raw.update(
            {
                "analysis_lon_min": lon_min,
                "analysis_lon_max": lon_max,
                "analysis_lat_min": lat_min,
                "analysis_lat_max": lat_max,
                "detect_ridge": False,
                "enable_meridional_valley_tracks": True,
                "meridional_track_lon_min": lon_min,
                "meridional_track_lon_max": lon_max,
                "meridional_track_lat_min": lat_min,
                "meridional_track_lat_max": lat_max,
                "meridional_track_max_lines": max_lines,
                "max_lines": max_lines,
                "min_length_km": min_length_km,
                "meridional_track_min_depth_gpm": min_depth_gpm,
                "meridional_track_min_mean_depth_gpm": min_mean_depth_gpm,
                "meridional_track_min_peak_depth_gpm": min_peak_depth_gpm,
                "meridional_track_max_lon_step_deg": 2.8,
                "meridional_track_max_gap_rows": 2,
                "meridional_track_min_points": 4,
                "meridional_track_min_lat_span_deg": 4.0,
            }
        )
        return output

    def _regional_meridional_tracks(
        z500,
        lat,
        lon,
        thresholds: dict | None,
        vorticity500,
    ) -> list[dict]:
        regions = [
            {
                "name": "south_china_hainan",
                "lon_min": 102.0,
                "lon_max": 115.0,
                "lat_min": 13.0,
                "lat_max": 31.0,
                "max_lines": 1,
                "min_length_km": 250.0,
                "min_depth_gpm": 0.25,
                "min_mean_depth_gpm": 0.35,
                "min_peak_depth_gpm": 0.70,
            },
            {
                "name": "mongolia_russia_west",
                "lon_min": 88.0,
                "lon_max": 113.0,
                "lat_min": 32.0,
                "lat_max": 55.0,
                "max_lines": 2,
                "min_length_km": 320.0,
                "min_depth_gpm": 0.40,
                "min_mean_depth_gpm": 0.55,
                "min_peak_depth_gpm": 1.00,
            },
        ]
        tracks: list[dict] = []
        for region in regions:
            regional = _regional_thresholds(
                thresholds,
                lon_min=region["lon_min"],
                lon_max=region["lon_max"],
                lat_min=region["lat_min"],
                lat_max=region["lat_max"],
                max_lines=region["max_lines"],
                min_length_km=region["min_length_km"],
                min_depth_gpm=region["min_depth_gpm"],
                min_mean_depth_gpm=region["min_mean_depth_gpm"],
                min_peak_depth_gpm=region["min_peak_depth_gpm"],
            )
            candidates, _ = _original_detect_trough_ridge(
                z500,
                lat,
                lon,
                regional,
                vorticity500=vorticity500,
            )
            for feature in candidates:
                if not _is_meridional_track(feature):
                    continue
                copied = {
                    **feature,
                    "properties": {
                        **(feature.get("properties") or {}),
                        "supplement_region": region["name"],
                    },
                }
                if not _is_duplicate(copied, tracks, 180.0):
                    tracks.append(copied)
        return tracks

    def _merge_tracks(
        contour_troughs: list[dict],
        supplemental: list[dict],
        original_troughs: list[dict],
    ) -> list[dict]:
        output = list(contour_troughs)
        for feature in supplemental:
            if not _is_duplicate(feature, output):
                output.append(feature)
        if output:
            return output
        # Preserve the old operational fallback when neither automatic contour
        # tips nor regional valley tracks can form a valid line.
        return original_troughs

    def _detect_trough_ridge_with_contour_seeds(
        z500,
        lat,
        lon,
        thresholds=None,
        vorticity500=None,
    ):
        effective = _copy_thresholds(thresholds)
        original_troughs, ridges = _original_detect_trough_ridge(
            z500,
            lat,
            lon,
            effective,
            vorticity500=vorticity500,
        )
        raw = _raw_thresholds(effective)
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
            supplemental = _regional_meridional_tracks(
                z500,
                lat,
                lon,
                effective,
                vorticity500,
            )
        except Exception:
            # Operational fallback: a contour extraction failure must not remove
            # the established height-trough product.
            return original_troughs, ridges
        return _merge_tracks(contour_troughs, supplemental, original_troughs), ridges

    _detect_trough_ridge_with_contour_seeds._contour_seeded_wrapper = True
    _trough_ridge.detect_trough_ridge = _detect_trough_ridge_with_contour_seeds
