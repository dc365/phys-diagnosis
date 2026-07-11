from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_sounding_optimized() -> None:
    path = ROOT / "weather_diag/diagnosis/sounding_optimized.py"
    replace_once(
        path,
        "from weather_diag.diagnosis.objective_analysis import ObjectiveAnalysisConfig, objective_analysis_field\n",
        "from weather_diag.diagnosis.objective_analysis import ObjectiveAnalysisConfig, objective_analysis_field\n"
        "from weather_diag.diagnosis.sounding_z500_adaptive import adaptive_station_z500\n",
    )
    replace_once(
        path,
        'Z500_ANALYSIS_VERSION = "sounding_z500_synoptic_v2"',
        'Z500_ANALYSIS_VERSION = "sounding_z500_synoptic_v3"',
    )
    old = '''    z_background = _background_surface(frame, "geopotential_height_m", lat, lon)
    z = objective_analysis_field(
        frame,
        "geopotential_height_m",
        lat,
        lon,
        config=SOUNDING_ANALYSIS_CONFIG,
        background=z_background,
    )
    z.quality.update(
        {
            "analysis_version": Z500_ANALYSIS_VERSION,
            "field_role": "synoptic_z500",
            "background_method": "robust_quadratic_station_trend",
            "vertical_interpolated_station_count": int(frame.attrs.get("vertical_interpolated_station_count", 0)),
            "vertical_exact_station_count": int(frame.attrs.get("vertical_exact_station_count", 0)),
        }
    )
'''
    new = '''    z_background = _background_surface(frame, "geopotential_height_m", lat, lon)
    z_baseline = objective_analysis_field(
        frame,
        "geopotential_height_m",
        lat,
        lon,
        config=SOUNDING_ANALYSIS_CONFIG,
        background=z_background,
    )
    z = adaptive_station_z500(frame, lat, lon, z_baseline)
    z.quality.update(
        {
            "analysis_version": Z500_ANALYSIS_VERSION,
            "vertical_interpolated_station_count": int(frame.attrs.get("vertical_interpolated_station_count", 0)),
            "vertical_exact_station_count": int(frame.attrs.get("vertical_exact_station_count", 0)),
        }
    )
'''
    replace_once(path, old, new)


def patch_contour_trough() -> None:
    path = ROOT / "weather_diag/features/contour_trough.py"
    old = '''    eligible = [*multi_level, *strong_single]
    if not eligible:
        return [], float("inf")
    threshold = _otsu(
        np.asarray([cluster["score"] for cluster in eligible]),
        cfg.contour_seed_otsu_bins,
    )
    selected = (
        list(multi_level)
        if multi_level
        else [cluster for cluster in strong_single if cluster["score"] >= threshold]
    )
    if not selected:
        selected = [max(eligible, key=lambda cluster: cluster["score"])]
'''
    new = '''    eligible = [*multi_level, *strong_single]
    if not eligible:
        return [], float("inf")

    # Multi-level contour-tip clusters are intrinsically strong seeds.  Keep them
    # all, but do not discard exceptional single-level tips merely because another
    # system happened to have multi-level support elsewhere in the domain.
    single_threshold = _otsu(
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
    threshold = single_threshold
    if not selected:
        selected = [max(eligible, key=lambda cluster: cluster["score"])]
'''
    replace_once(path, old, new)

    old_bounds = '''def _seed_bounds(seed: dict, cfg: ContourSeededTroughConfig) -> tuple[float, float, float, float]:
    lat_span = max(0.0, float(seed["tip_lat_max"] - seed["tip_lat_min"]))
    lat_margin = max(2.5, min(4.0, 0.20 * lat_span + 1.5))
    lon_span = max(0.0, float(seed["tip_lon_max"] - seed["tip_lon_min"]))
    lon_margin = max(3.0, min(5.0, 0.50 * lon_span + 2.0))
    return (
        max(cfg.analysis_lat_min, float(seed["tip_lat_min"]) - lat_margin),
        min(cfg.analysis_lat_max, float(seed["tip_lat_max"]) + lat_margin),
        max(cfg.analysis_lon_min, float(seed["tip_lon_min"]) - lon_margin),
        min(cfg.analysis_lon_max, float(seed["tip_lon_max"]) + lon_margin),
    )
'''
    new_bounds = '''def _seed_bounds(seed: dict, cfg: ContourSeededTroughConfig) -> tuple[float, float, float, float]:
    lat_span = max(0.0, float(seed["tip_lat_max"] - seed["tip_lat_min"]))
    lon_span = max(0.0, float(seed["tip_lon_max"] - seed["tip_lon_min"]))
    seed_lat = float(seed["lat"])

    if seed_lat >= 34.0:
        # Northern contour tips are often the equatorward end of a much longer
        # Mongolia/Russia trough.  Allow the valley trace to continue north until
        # the objective height minimum actually disappears instead of stopping a
        # fixed 2.5-4 degrees from the seed cluster.
        south_margin = max(5.0, min(9.0, 0.35 * lat_span + 4.0))
        north_margin = max(9.0, min(15.0, 0.65 * lat_span + 8.0))
        lon_margin = max(4.0, min(7.0, 0.65 * lon_span + 3.0))
    else:
        south_margin = max(3.0, min(5.0, 0.25 * lat_span + 2.0))
        north_margin = max(3.5, min(6.0, 0.30 * lat_span + 2.5))
        lon_margin = max(3.0, min(5.5, 0.50 * lon_span + 2.0))

    return (
        max(cfg.analysis_lat_min, float(seed["tip_lat_min"]) - south_margin),
        min(cfg.analysis_lat_max, float(seed["tip_lat_max"]) + north_margin),
        max(cfg.analysis_lon_min, float(seed["tip_lon_min"]) - lon_margin),
        min(cfg.analysis_lon_max, float(seed["tip_lon_max"]) + lon_margin),
    )
'''
    replace_once(path, old_bounds, new_bounds)


def main() -> None:
    patch_sounding_optimized()
    patch_contour_trough()

    output_dir = ROOT / "artifacts/sounding-h500/patched-files"
    for relative in [
        Path("weather_diag/diagnosis/sounding_optimized.py"),
        Path("weather_diag/features/contour_trough.py"),
    ]:
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text((ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")


if __name__ == "__main__":
    main()
