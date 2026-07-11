from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg", force=True)
from matplotlib import pyplot as plt

from weather_diag.diagnosis.objective_analysis import mask_unsupported
from weather_diag.diagnosis.sounding_optimized import diagnose_sounding_situation
from weather_diag.io.contours import contours_to_geojson


DEFAULT_DATA_DIR = Path(
    "test_datas/regional_radiosonde_5N55N_50E160E_20260624_20260625"
)
DEFAULT_FILE = DEFAULT_DATA_DIR / "regional_radiosonde_5N55N_50E160E_20260625_20BJT.csv"


def _line_coordinates(system: dict) -> np.ndarray:
    geometry = system.get("geometry") or {}
    coordinates = np.asarray(geometry.get("coordinates") or [], dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[1] < 2:
        return np.empty((0, 2), dtype=float)
    return coordinates[:, :2]


def _contour_zone_summary(contours: dict, bounds: tuple[float, float, float, float]) -> dict:
    lon_min, lat_min, lon_max, lat_max = bounds
    levels: dict[str, int] = {}
    feature_count = 0
    for feature in contours.get("features") or []:
        coordinates = np.asarray((feature.get("geometry") or {}).get("coordinates") or [], dtype=float)
        if coordinates.ndim != 2 or coordinates.shape[1] < 2:
            continue
        intersects = (
            (coordinates[:, 0] >= lon_min)
            & (coordinates[:, 0] <= lon_max)
            & (coordinates[:, 1] >= lat_min)
            & (coordinates[:, 1] <= lat_max)
        )
        if not np.any(intersects):
            continue
        feature_count += 1
        value = str((feature.get("properties") or {}).get("value"))
        levels[value] = levels.get(value, 0) + 1
    return {"feature_count": feature_count, "levels": levels}


def _system_zone_summary(systems: list[dict], bounds: tuple[float, float, float, float]) -> list[dict]:
    lon_min, lat_min, lon_max, lat_max = bounds
    output = []
    for system in systems:
        coordinates = _line_coordinates(system)
        if coordinates.size == 0:
            continue
        intersects = (
            (coordinates[:, 0] >= lon_min)
            & (coordinates[:, 0] <= lon_max)
            & (coordinates[:, 1] >= lat_min)
            & (coordinates[:, 1] <= lat_max)
        )
        if not np.any(intersects):
            continue
        output.append(
            {
                "id": system.get("id"),
                "feature_type": system.get("feature_type"),
                "method": system.get("method"),
                "method_detail": system.get("method_detail"),
                "candidate_source": system.get("candidate_source"),
                "axis_length_km": system.get("axis_length_km"),
                "lon_min": float(np.nanmin(coordinates[:, 0])),
                "lon_max": float(np.nanmax(coordinates[:, 0])),
                "lat_min": float(np.nanmin(coordinates[:, 1])),
                "lat_max": float(np.nanmax(coordinates[:, 1])),
            }
        )
    return output


def render(csv_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = diagnose_sounding_situation(csv_path, pressure_level=500)
    field = result["analysis_fields"]["z500"]
    lat = np.asarray(field["lat"], dtype=float)
    lon = np.asarray(field["lon"], dtype=float)
    values = np.asarray(field["values"], dtype=float)
    supported = mask_unsupported(values * 0.1, field.get("support_mask"))
    contours = contours_to_geojson(
        "z500",
        "500hPa geopotential height",
        "dagpm",
        supported,
        lat=lat,
        lon=lon,
        interval=4.0,
        min_length_km=120.0,
        smooth=True,
        smooth_iterations=2,
        simplify_tolerance_deg=0.012,
    )

    fig, ax = plt.subplots(figsize=(14, 7.5), dpi=150)
    levels = np.arange(
        np.ceil(np.nanmin(supported) / 4.0) * 4.0,
        np.floor(np.nanmax(supported) / 4.0) * 4.0 + 0.1,
        4.0,
    )
    contour_set = ax.contour(lon, lat, np.ma.masked_invalid(supported), levels=levels, colors="tab:blue", linewidths=0.9)
    ax.clabel(contour_set, inline=True, fontsize=7, fmt="%d")

    troughs = []
    for system in result.get("systems") or []:
        if system.get("feature_type") not in {"trough", "trough_candidate"}:
            continue
        coordinates = _line_coordinates(system)
        if coordinates.shape[0] < 2:
            continue
        troughs.append(system)
        ax.plot(coordinates[:, 0], coordinates[:, 1], color="purple", linewidth=2.6)
        ax.text(
            float(coordinates[len(coordinates) // 2, 0]),
            float(coordinates[len(coordinates) // 2, 1]),
            str(system.get("candidate_source") or "trough"),
            fontsize=6,
            color="purple",
        )

    stations = result.get("station_features", {}).get("features") or []
    station_lon = []
    station_lat = []
    for station in stations:
        coordinates = (station.get("geometry") or {}).get("coordinates") or []
        if len(coordinates) >= 2:
            station_lon.append(float(coordinates[0]))
            station_lat.append(float(coordinates[1]))
    if station_lon:
        ax.scatter(station_lon, station_lat, s=3, color="black", alpha=0.35)

    ax.set_xlim(50, 150)
    ax.set_ylim(10, 55)
    ax.set_xticks(np.arange(50, 151, 10))
    ax.set_yticks(np.arange(10, 56, 5))
    ax.grid(True, linewidth=0.35, alpha=0.4)
    ax.set_title(f"{result.get('observation_time')} station-only H500 analysis")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    fig.tight_layout()
    fig.savefig(output_dir / "sounding_h500_analysis.png")
    plt.close(fig)

    reference = next(DEFAULT_DATA_DIR.glob("SEVP_NMC_WESA*.jpeg"), None)
    if reference is not None:
        (output_dir / "reference_nmc.jpeg").write_bytes(reference.read_bytes())

    zones = {
        "hainan": (104.0, 13.0, 115.0, 26.0),
        "northeast": (112.0, 27.0, 145.0, 52.0),
        "mongolia_russia_west": (92.0, 32.0, 111.0, 55.0),
        "russia_far_east": (112.0, 35.0, 132.0, 55.0),
    }
    report = {
        "csv_path": str(csv_path),
        "observation_time": result.get("observation_time"),
        "quality": field.get("quality"),
        "contour_count": len(contours.get("features") or []),
        "trough_count": len(troughs),
        "zones": {
            name: {
                "contours": _contour_zone_summary(contours, bounds),
                "troughs": _system_zone_summary(troughs, bounds),
            }
            for name, bounds in zones.items()
        },
    }
    (output_dir / "sounding_h500_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/sounding-h500"))
    args = parser.parse_args()
    render(args.csv, args.output_dir)
