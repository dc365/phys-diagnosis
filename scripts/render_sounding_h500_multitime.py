from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import matplotlib
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

matplotlib.use("Agg", force=True)
from matplotlib import pyplot as plt

from weather_diag.diagnosis.objective_analysis import mask_unsupported
from weather_diag.diagnosis.sounding_optimized import diagnose_sounding_situation
from weather_diag.io.contours import contours_to_geojson


DATA_DIR = Path(
    "test_datas/regional_radiosonde_5N55N_50E160E_20260624_20260625"
)
DEFAULT_OUTPUT = Path("artifacts/sounding-h500-multitime")
REFERENCE_DOMAIN = (50.0, 130.0, 10.0, 50.0)
# The NMC chart frame is stable across the archived JPEGs. Fractions make the
# mapping robust to minor image-size differences.
REFERENCE_FRAME_FRACTIONS = (0.0352, 0.0484, 0.9680, 0.9645)


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _cycle_key(csv_path: Path) -> str:
    stem = csv_path.stem
    marker = "regional_radiosonde_5N55N_50E160E_"
    return stem[len(marker) :] if stem.startswith(marker) else stem


def _reference_for_cycle(csv_path: Path) -> Path | None:
    key = _cycle_key(csv_path)
    # 20260625_20BJT -> 2026-06-25 12UTC
    timestamp = datetime.strptime(key, "%Y%m%d_%HBJT") - timedelta(hours=8)
    compact = timestamp.strftime("%Y%m%d%H")
    matches = sorted(DATA_DIR.glob(f"SEVP_NMC_WESA*{compact}*.jpeg"))
    if not matches:
        matches = sorted(DATA_DIR.glob(f"SEVP_NMC_WESA*{compact}*.jpg"))
    return matches[0] if matches else None


def _line_coordinates(feature: dict[str, Any]) -> np.ndarray:
    geometry = feature.get("geometry") or {}
    coordinates = np.asarray(geometry.get("coordinates") or [], dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[0] < 2 or coordinates.shape[1] < 2:
        return np.empty((0, 2), dtype=float)
    return coordinates[:, :2]


def _troughs(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in result.get("systems") or []
        if item.get("feature_type") in {"trough", "trough_candidate"}
        and _line_coordinates(item).shape[0] >= 2
    ]


def _diagnostic_shear_lines(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the regional Hainan shear supplement for NMC brown-line checks."""
    return [
        item
        for item in result.get("systems") or []
        if item.get("feature_type") == "shear_line"
        and item.get("candidate_source") == "south_china_588_deformation_track"
        and _line_coordinates(item).shape[0] >= 2
    ]


def _contours(field: dict[str, Any]) -> dict[str, Any]:
    values = np.asarray(field["values"], dtype=float)
    support = np.asarray(field.get("support_mask"), dtype=bool)
    data = mask_unsupported(values * 0.1, support)
    return contours_to_geojson(
        "z500",
        "500hPa geopotential height",
        "dagpm",
        data,
        lat=np.asarray(field["lat"], dtype=float),
        lon=np.asarray(field["lon"], dtype=float),
        interval=4.0,
        min_length_km=120.0,
        smooth=True,
        smooth_iterations=2,
        simplify_tolerance_deg=0.012,
    )


def _reference_frame(image: Image.Image) -> tuple[int, int, int, int]:
    width, height = image.size
    left_f, top_f, right_f, bottom_f = REFERENCE_FRAME_FRACTIONS
    return (
        int(round(left_f * width)),
        int(round(top_f * height)),
        int(round(right_f * width)),
        int(round(bottom_f * height)),
    )


def _lonlat_to_pixel(
    lon: np.ndarray,
    lat: np.ndarray,
    image: Image.Image,
) -> tuple[np.ndarray, np.ndarray]:
    left, top, right, bottom = _reference_frame(image)
    lon_min, lon_max, lat_min, lat_max = REFERENCE_DOMAIN
    x = left + (np.asarray(lon, dtype=float) - lon_min) / (lon_max - lon_min) * (right - left)
    y = top + (lat_max - np.asarray(lat, dtype=float)) / (lat_max - lat_min) * (bottom - top)
    return x, y


def _extract_reference_masks(image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    rgb = np.asarray(image.convert("RGB"), dtype=np.int16)
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]

    # Blue height contours and labels. The component cleanup removes isolated
    # anti-aliased pixels but deliberately keeps contour labels connected to lines.
    blue_mask = (
        (blue >= 95)
        & (blue - red >= 35)
        & (blue - green >= 20)
        & (red <= 150)
    )

    # Operational troughs are thick dark-brown strokes. Red temperature contours
    # are brighter and thinner, so colour + local thickness separates most of them.
    brown_candidate = (
        (red >= 35)
        & (red <= 175)
        & (red - green >= 24)
        & (red - blue >= 24)
        & (green <= 105)
        & (blue <= 105)
    )
    thickness = ndimage.distance_transform_edt(brown_candidate)
    brown_core = thickness >= 1.35
    brown_mask = ndimage.binary_dilation(brown_core, iterations=2) & brown_candidate

    left, top, right, bottom = _reference_frame(image)
    frame = np.zeros(blue_mask.shape, dtype=bool)
    frame[top : bottom + 1, left : right + 1] = True
    blue_mask &= frame
    brown_mask &= frame

    # Remove tiny colour fragments and the large CMA logo/text blocks by requiring
    # elongated connected components in the chart body.
    brown_labels, count = ndimage.label(brown_mask)
    cleaned_brown = np.zeros_like(brown_mask)
    for label_id in range(1, count + 1):
        ys, xs = np.where(brown_labels == label_id)
        if ys.size < 45:
            continue
        if np.ptp(xs) + np.ptp(ys) < 45:
            continue
        cleaned_brown[ys, xs] = True

    blue_labels, count = ndimage.label(blue_mask)
    cleaned_blue = np.zeros_like(blue_mask)
    for label_id in range(1, count + 1):
        ys, xs = np.where(blue_labels == label_id)
        if ys.size >= 12:
            cleaned_blue[ys, xs] = True
    return cleaned_blue, cleaned_brown


def _rasterize_geo_lines(
    lines: Iterable[np.ndarray],
    image: Image.Image,
    *,
    width: int,
) -> np.ndarray:
    canvas = Image.new("1", image.size, 0)
    draw = ImageDraw.Draw(canvas)
    lon_min, lon_max, lat_min, lat_max = REFERENCE_DOMAIN
    for coordinates in lines:
        coords = np.asarray(coordinates, dtype=float)
        if coords.ndim != 2 or coords.shape[0] < 2:
            continue
        inside = (
            (coords[:, 0] >= lon_min - 2.0)
            & (coords[:, 0] <= lon_max + 2.0)
            & (coords[:, 1] >= lat_min - 2.0)
            & (coords[:, 1] <= lat_max + 2.0)
        )
        if np.count_nonzero(inside) < 2:
            continue
        selected = coords[inside]
        x, y = _lonlat_to_pixel(selected[:, 0], selected[:, 1], image)
        draw.line([(float(px), float(py)) for px, py in zip(x, y)], fill=1, width=width)
    return np.asarray(canvas, dtype=bool)


def _symmetric_distance(reference: np.ndarray, generated: np.ndarray) -> dict[str, float | None]:
    if not reference.any() or not generated.any():
        return {"generated_to_reference_px": None, "reference_to_generated_px": None, "symmetric_px": None}
    to_reference = ndimage.distance_transform_edt(~reference)
    to_generated = ndimage.distance_transform_edt(~generated)
    generated_distance = float(np.mean(to_reference[generated]))
    reference_distance = float(np.mean(to_generated[reference]))
    return {
        "generated_to_reference_px": round(generated_distance, 3),
        "reference_to_generated_px": round(reference_distance, 3),
        "symmetric_px": round((generated_distance + reference_distance) / 2.0, 3),
    }


def _render_analysis(
    result: dict[str, Any],
    contours: dict[str, Any],
    output_path: Path,
) -> None:
    field = result["analysis_fields"]["z500"]
    lat = np.asarray(field["lat"], dtype=float)
    lon = np.asarray(field["lon"], dtype=float)
    supported = mask_unsupported(
        np.asarray(field["values"], dtype=float) * 0.1,
        np.asarray(field.get("support_mask"), dtype=bool),
    )
    fig, axis = plt.subplots(figsize=(15.0, 7.5), dpi=150)
    finite = supported[np.isfinite(supported)]
    levels = np.arange(
        np.ceil(float(np.nanmin(finite)) / 4.0) * 4.0,
        np.floor(float(np.nanmax(finite)) / 4.0) * 4.0 + 0.1,
        4.0,
    )
    contour_set = axis.contour(lon, lat, np.ma.masked_invalid(supported), levels=levels, linewidths=0.9)
    axis.clabel(contour_set, inline=True, fontsize=7, fmt="%d")
    for trough in _troughs(result):
        coordinates = _line_coordinates(trough)
        axis.plot(coordinates[:, 0], coordinates[:, 1], linewidth=2.5)
        midpoint = coordinates[len(coordinates) // 2]
        axis.text(
            float(midpoint[0]),
            float(midpoint[1]),
            str(trough.get("id") or trough.get("candidate_source") or "trough"),
            fontsize=6,
        )
    for shear in _diagnostic_shear_lines(result):
        coordinates = _line_coordinates(shear)
        axis.plot(coordinates[:, 0], coordinates[:, 1], linewidth=2.5, linestyle="--")
        midpoint = coordinates[len(coordinates) // 2]
        axis.text(float(midpoint[0]), float(midpoint[1]), "Hainan shear", fontsize=6)
    station_lon: list[float] = []
    station_lat: list[float] = []
    for station in (result.get("station_features") or {}).get("features") or []:
        coordinates = (station.get("geometry") or {}).get("coordinates") or []
        if len(coordinates) >= 2:
            station_lon.append(float(coordinates[0]))
            station_lat.append(float(coordinates[1]))
    if station_lon:
        axis.scatter(station_lon, station_lat, s=3, alpha=0.28)
    axis.set_xlim(50.0, 150.0)
    axis.set_ylim(5.0, 55.0)
    axis.set_xticks(np.arange(50.0, 151.0, 10.0))
    axis.set_yticks(np.arange(5.0, 56.0, 5.0))
    axis.grid(True, linewidth=0.35, alpha=0.4)
    axis.set_title(f"{result.get('observation_time')} station-only H500")
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def _render_overlay(
    reference: Image.Image,
    blue_reference: np.ndarray,
    brown_reference: np.ndarray,
    generated_contours: np.ndarray,
    generated_troughs: np.ndarray,
    output_path: Path,
) -> None:
    base = np.asarray(reference.convert("RGB"), dtype=np.uint8).copy()
    overlay = np.zeros_like(base)
    overlay[blue_reference] = (0, 180, 255)
    overlay[brown_reference] = (255, 130, 0)
    overlay[generated_contours] = (40, 255, 40)
    overlay[generated_troughs] = (255, 0, 255)
    blended = np.clip(base.astype(float) * 0.58 + overlay.astype(float) * 0.72, 0, 255).astype(np.uint8)
    Image.fromarray(blended).save(output_path)


def render_cycle(csv_path: Path, output_dir: Path) -> dict[str, Any]:
    key = _cycle_key(csv_path)
    cycle_dir = output_dir / key
    cycle_dir.mkdir(parents=True, exist_ok=True)
    result = diagnose_sounding_situation(csv_path, pressure_level=500)
    field = result["analysis_fields"]["z500"]
    contours = _contours(field)
    troughs = _troughs(result)
    shear_lines = _diagnostic_shear_lines(result)

    _render_analysis(result, contours, cycle_dir / "analysis.png")
    np.savez_compressed(
        cycle_dir / "fields.npz",
        lat=np.asarray(field["lat"], dtype=float),
        lon=np.asarray(field["lon"], dtype=float),
        z500=np.asarray(field["values"], dtype=float),
        support_distance_km=np.asarray(field.get("support_distance_km"), dtype=float),
        support_mask=np.asarray(field.get("support_mask"), dtype=bool),
        t500=np.asarray(result["analysis_fields"]["t500"]["values"], dtype=float),
        u500=np.asarray(result["analysis_fields"]["u500"]["values"], dtype=float),
        v500=np.asarray(result["analysis_fields"]["v500"]["values"], dtype=float),
    )

    report: dict[str, Any] = {
        "cycle": key,
        "csv": str(csv_path),
        "observation_time": result.get("observation_time"),
        "quality": _jsonable(field.get("quality") or {}),
        "contour_count": len(contours.get("features") or []),
        "trough_count": len(troughs),
        "hainan_shear_count": len(shear_lines),
        "troughs": [
            {
                **{key: _jsonable(value) for key, value in item.items() if key != "geometry"},
                "coordinates": _line_coordinates(item).tolist(),
            }
            for item in troughs
        ],
        "hainan_shear": [
            {
                **{key: _jsonable(value) for key, value in item.items() if key != "geometry"},
                "coordinates": _line_coordinates(item).tolist(),
            }
            for item in shear_lines
        ],
    }

    reference_path = _reference_for_cycle(csv_path)
    if reference_path is not None:
        shutil.copy2(reference_path, cycle_dir / "reference.jpeg")
        reference = Image.open(reference_path).convert("RGB")
        blue_reference, brown_reference = _extract_reference_masks(reference)
        contour_lines = [
            np.asarray((feature.get("geometry") or {}).get("coordinates") or [], dtype=float)
            for feature in contours.get("features") or []
        ]
        trough_lines = [_line_coordinates(item) for item in troughs]
        shear_lines_coordinates = [_line_coordinates(item) for item in shear_lines]
        generated_contours = _rasterize_geo_lines(contour_lines, reference, width=2)
        generated_troughs = _rasterize_geo_lines(
            [*trough_lines, *shear_lines_coordinates],
            reference,
            width=5,
        )
        report["reference"] = str(reference_path)
        report["contour_distance"] = _symmetric_distance(blue_reference, generated_contours)
        report["trough_distance"] = _symmetric_distance(brown_reference, generated_troughs)
        _render_overlay(
            reference,
            blue_reference,
            brown_reference,
            generated_contours,
            generated_troughs,
            cycle_dir / "overlay.png",
        )
        Image.fromarray((blue_reference * 255).astype(np.uint8)).save(cycle_dir / "reference_blue_mask.png")
        Image.fromarray((brown_reference * 255).astype(np.uint8)).save(cycle_dir / "reference_brown_mask.png")
    else:
        report["reference"] = None

    (cycle_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def render_all(output_dir: Path = DEFAULT_OUTPUT) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_files = sorted(DATA_DIR.glob("regional_radiosonde_5N55N_50E160E_202606*_??BJT.csv"))
    reports = [render_cycle(csv_path, output_dir) for csv_path in csv_files]
    summary = {
        "cycle_count": len(reports),
        "cycles": reports,
        "mean_contour_symmetric_px": float(
            np.nanmean(
                [
                    (item.get("contour_distance") or {}).get("symmetric_px", np.nan)
                    for item in reports
                ]
            )
        ),
        "mean_trough_symmetric_px": float(
            np.nanmean(
                [
                    (item.get("trough_distance") or {}).get("symmetric_px", np.nan)
                    for item in reports
                ]
            )
        ),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    render_all()
