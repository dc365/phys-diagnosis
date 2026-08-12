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

    def _install_contour_runtime_patches(module) -> None:
        """Install sounding-only seed selection and trace-bound improvements.

        The detector stays lazily imported, so model/NAFP feature paths do not pay
        the Matplotlib startup cost. Multi-level and exceptional single-level tips
        are retained together, and northern tips may trace farther along a
        continuous height valley.
        """

        if getattr(module, "_sounding_contour_v3_patch", False):
            return

        def _select_seeds(clusters: list[dict], cfg):
            multi_level = [
                cluster
                for cluster in clusters
                if cluster["level_count"] >= cfg.contour_seed_min_levels
            ]
            strong_single = [
                cluster
                for cluster in clusters
                if cluster["level_count"] < cfg.contour_seed_min_levels
                and cluster["depth_mean_deg"]
                >= 2.0 * cfg.contour_tip_min_depth_deg
            ]
            eligible = [*multi_level, *strong_single]
            if not eligible:
                return [], float("inf")

            single_threshold = module._otsu(
                np.asarray([cluster["score"] for cluster in strong_single]),
                cfg.contour_seed_otsu_bins,
            )
            selected = [
                *multi_level,
                *[
                    cluster
                    for cluster in strong_single
                    if cluster["score"] >= single_threshold
                ],
            ]
            if not selected:
                selected = [max(eligible, key=lambda cluster: cluster["score"])]

            kept: list[dict] = []
            for item in sorted(
                selected,
                key=lambda cluster: (cluster["level_count"], cluster["score"]),
                reverse=True,
            ):
                point = np.asarray([item["lon"], item["lat"]], dtype=float)
                if any(
                    module._distance_km(
                        point,
                        np.asarray([old["lon"], old["lat"]], dtype=float),
                    )
                    < min(cfg.contour_cluster_radius_km * 0.40, 360.0)
                    for old in kept
                ):
                    continue
                kept.append(item)
            return kept, single_threshold

        def _seed_bounds(seed: dict, cfg):
            lat_span = max(
                0.0,
                float(seed["tip_lat_max"] - seed["tip_lat_min"]),
            )
            lon_span = max(
                0.0,
                float(seed["tip_lon_max"] - seed["tip_lon_min"]),
            )
            seed_lat = float(seed["lat"])
            if seed_lat >= 34.0:
                south_margin = max(5.0, min(9.0, 0.35 * lat_span + 4.0))
                north_margin = max(9.0, min(15.0, 0.65 * lat_span + 8.0))
                lon_margin = max(4.0, min(7.0, 0.65 * lon_span + 3.0))
            else:
                south_margin = max(3.0, min(5.0, 0.25 * lat_span + 2.0))
                north_margin = max(3.5, min(6.0, 0.30 * lat_span + 2.5))
                lon_margin = max(3.0, min(5.5, 0.50 * lon_span + 2.0))
            return (
                max(
                    cfg.analysis_lat_min,
                    float(seed["tip_lat_min"]) - south_margin,
                ),
                min(
                    cfg.analysis_lat_max,
                    float(seed["tip_lat_max"]) + north_margin,
                ),
                max(
                    cfg.analysis_lon_min,
                    float(seed["tip_lon_min"]) - lon_margin,
                ),
                min(
                    cfg.analysis_lon_max,
                    float(seed["tip_lon_max"]) + lon_margin,
                ),
            )

        module._select_seeds = _select_seeds
        module._seed_bounds = _seed_bounds
        module._sounding_contour_v3_patch = True

    def _coordinates(feature: dict) -> np.ndarray:
        values = np.asarray(
            (feature.get("geometry") or {}).get("coordinates") or [],
            dtype=float,
        )
        if values.ndim != 2 or values.shape[0] < 2 or values.shape[1] < 2:
            return np.empty((0, 2), dtype=float)
        return values[:, :2]

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
        min_lat_span_deg: float,
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
                "meridional_track_min_lat_span_deg": min_lat_span_deg,
            }
        )
        return output

    def _direct_valley_tracks(
        z500,
        lat,
        lon,
        regional_thresholds: dict,
        vorticity500,
        *,
        region_name: str,
        global_domain: dict,
    ) -> list[dict]:
        """Build regional valley tracks without component-overlap suppression."""

        z, lat_values, lon_values, vorticity = _trough_ridge._prepare_lat_lon_field(
            _trough_ridge._maybe_geopotential_to_height(np.asarray(z500, dtype=float)),
            lat,
            lon,
            vorticity500,
        )
        cfg = _trough_ridge._cfg_from_thresholds(regional_thresholds)
        dy_km, dx_km = _trough_ridge._grid_spacing_km(lat_values, lon_values)
        sigma_y = max(cfg.min_sigma_grid, cfg.smooth_radius_km / max(dy_km, 1.0))
        sigma_x = max(cfg.min_sigma_grid, cfg.smooth_radius_km / max(dx_km, 1.0))
        z_large = _trough_ridge._nan_gaussian(z, (sigma_y, sigma_x))
        score, maps = _trough_ridge._build_score(
            z_large,
            lat_values,
            lon_values,
            cfg,
            "trough",
            vorticity,
        )
        second_y = max(0.0, cfg.second_smooth_radius_km / max(dy_km, 1.0))
        second_x = max(0.0, cfg.second_smooth_radius_km / max(dx_km, 1.0))
        score_smooth = (
            _trough_ridge._nan_gaussian(score, (second_y, second_x))
            if cfg.second_smooth_radius_km > 0
            else score
        )
        maps = {**maps, "score": score_smooth}

        features: list[dict] = []
        for rank, track in enumerate(
            _trough_ridge._zonal_valley_tracks(z, lat_values, lon_values, cfg),
            start=1,
        ):
            line = _trough_ridge._valley_track_to_line(
                track,
                z,
                lat_values,
                lon_values,
                score_smooth,
                maps,
                cfg,
            )
            if line is None:
                continue
            feature = _trough_ridge._feature_from_line(line, rank, "trough", cfg)
            properties = feature.get("properties") or {}
            properties.update(
                {
                    "id": f"trough_{region_name}_{rank:02d}",
                    "candidate_source": "meridional_valley_track",
                    "supplement_region": region_name,
                    "analysis_domain": {
                        "lon_min": float(global_domain.get("analysis_lon_min", 60.0)),
                        "lon_max": float(global_domain.get("analysis_lon_max", 150.0)),
                        "lat_min": float(global_domain.get("analysis_lat_min", 15.0)),
                        "lat_max": float(global_domain.get("analysis_lat_max", 55.0)),
                    },
                }
            )
            feature["properties"] = properties
            features.append(feature)
        return features

    def _regional_meridional_tracks(
        z500,
        lat,
        lon,
        thresholds: dict | None,
        vorticity500,
    ) -> list[dict]:
        global_domain = _raw_thresholds(thresholds)
        regions = [
            {
                "name": "south_china_hainan",
                "lon_min": 105.0,
                "lon_max": 114.0,
                "lat_min": 13.0,
                "lat_max": 21.0,
                "max_lines": 1,
                "min_length_km": 240.0,
                "min_lat_span_deg": 3.0,
                "min_depth_gpm": 0.04,
                "min_mean_depth_gpm": 0.08,
                "min_peak_depth_gpm": 0.14,
            },
            {
                "name": "mongolia_russia_central",
                "lon_min": 99.0,
                "lon_max": 112.0,
                "lat_min": 38.0,
                "lat_max": 55.0,
                "max_lines": 1,
                "min_length_km": 500.0,
                "min_lat_span_deg": 6.0,
                "min_depth_gpm": 0.55,
                "min_mean_depth_gpm": 0.90,
                "min_peak_depth_gpm": 1.50,
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
                min_lat_span_deg=region["min_lat_span_deg"],
                min_depth_gpm=region["min_depth_gpm"],
                min_mean_depth_gpm=region["min_mean_depth_gpm"],
                min_peak_depth_gpm=region["min_peak_depth_gpm"],
            )
            candidates = _direct_valley_tracks(
                z500,
                lat,
                lon,
                regional,
                vorticity500,
                region_name=region["name"],
                global_domain=global_domain,
            )
            for feature in candidates:
                if not _is_duplicate(feature, tracks, 180.0):
                    tracks.append(feature)
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
            from . import contour_trough as _contour_trough

            _install_contour_runtime_patches(_contour_trough)
            contour_troughs = _contour_trough.detect_contour_seeded_troughs(
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
            return original_troughs, ridges
        return _merge_tracks(contour_troughs, supplemental, original_troughs), ridges

    _detect_trough_ridge_with_contour_seeds._contour_seeded_wrapper = True
    _trough_ridge.detect_trough_ridge = _detect_trough_ridge_with_contour_seeds
