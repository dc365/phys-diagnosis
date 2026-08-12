from __future__ import annotations

from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point
from shapely.ops import nearest_points, unary_union

TOPOLOGY_REFINEMENT_VERSION = "sounding_trough_shear_topology_v6"


@dataclass(frozen=True)
class _TopologyContext:
    troughs: tuple[dict[str, Any], ...]
    z500: np.ndarray
    u500: np.ndarray
    v500: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    support_distance_km: np.ndarray | None
    support_mask: np.ndarray | None


_LAST_CONTEXT: ContextVar[_TopologyContext | None] = ContextVar(
    "sounding_trough_shear_topology_context",
    default=None,
)


def _line_coordinates(system: dict[str, Any]) -> np.ndarray:
    values = np.asarray(
        (system.get("geometry") or {}).get("coordinates") or [],
        dtype=float,
    )
    if values.ndim != 2 or values.shape[0] < 2 or values.shape[1] < 2:
        return np.empty((0, 2), dtype=float)
    values = values[:, :2]
    return values[np.isfinite(values).all(axis=1)]


def _projection_scales(reference_lat: float) -> tuple[float, float]:
    x_scale = 111.32 * max(float(np.cos(np.deg2rad(reference_lat))), 0.20)
    return x_scale, 111.32


def _to_xy(coordinates: np.ndarray, reference_lat: float) -> np.ndarray:
    x_scale, y_scale = _projection_scales(reference_lat)
    values = np.asarray(coordinates, dtype=float)
    return np.column_stack([values[:, 0] * x_scale, values[:, 1] * y_scale])


def _to_lonlat(coordinates: np.ndarray, reference_lat: float) -> np.ndarray:
    x_scale, y_scale = _projection_scales(reference_lat)
    values = np.asarray(coordinates, dtype=float)
    return np.column_stack([values[:, 0] / x_scale, values[:, 1] / y_scale])


def _geometry_lines(geometry) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return [item for item in geometry.geoms if item.length > 0.0]
    if isinstance(geometry, GeometryCollection):
        output: list[LineString] = []
        for item in geometry.geoms:
            output.extend(_geometry_lines(item))
        return output
    return []


def _trough_clearance_km(system: dict[str, Any]) -> float:
    source = str(system.get("candidate_source") or "")
    if str(system.get("geometry_refinement_version") or "").startswith("sounding_z500_geometry"):
        return 105.0
    if source.startswith("closed_low_"):
        return 100.0
    metrics = system.get("path_metrics") or {}
    height_evidence = float(metrics.get("height_evidence_mean") or 0.0)
    return float(np.clip(75.0 + 45.0 * height_evidence, 75.0, 98.0))


def _normalise_field(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    sample = arr[np.asarray(valid, dtype=bool) & np.isfinite(arr)]
    if sample.size < 8:
        return np.zeros_like(arr, dtype=float)
    lower, upper = np.nanpercentile(sample, [45.0, 92.0])
    if not np.isfinite(upper - lower) or upper - lower <= 1.0e-12:
        return np.zeros_like(arr, dtype=float)
    return np.clip((arr - lower) / (upper - lower), 0.0, 2.0)


def _nan_gaussian(field: np.ndarray, sigma: float) -> np.ndarray:
    from scipy import ndimage

    arr = np.asarray(field, dtype=float)
    finite = np.isfinite(arr)
    if not finite.any():
        return np.full_like(arr, np.nan, dtype=float)
    values = ndimage.gaussian_filter(np.where(finite, arr, 0.0), sigma=sigma, mode="nearest")
    weights = ndimage.gaussian_filter(finite.astype(float), sigma=sigma, mode="nearest")
    output = np.full_like(arr, np.nan, dtype=float)
    np.divide(values, weights, out=output, where=weights > 1.0e-6)
    return output


def _shear_evidence_field(context: _TopologyContext) -> np.ndarray:
    u = _nan_gaussian(context.u500, 0.9)
    v = _nan_gaussian(context.v500, 0.9)
    lat = np.asarray(context.lat, dtype=float)
    lon = np.asarray(context.lon, dtype=float)
    cos_lat = np.maximum(np.cos(np.deg2rad(lat))[:, None], 0.20)
    dx = 111_320.0 * cos_lat
    dy = 111_320.0
    dudx = np.gradient(u, lon, axis=1, edge_order=1) / dx
    dvdx = np.gradient(v, lon, axis=1, edge_order=1) / dx
    dudy = np.gradient(u, lat, axis=0, edge_order=1) / dy
    dvdy = np.gradient(v, lat, axis=0, edge_order=1) / dy
    vorticity = np.maximum(dvdx - dudy, 0.0)
    convergence = np.maximum(-(dudx + dvdy), 0.0)
    deformation = np.hypot(dudx - dvdy, dvdx + dudy)
    speed = np.hypot(u, v)
    unit_u = u / np.maximum(speed, 0.5)
    unit_v = v / np.maximum(speed, 0.5)
    direction_gradient = np.hypot(
        np.gradient(unit_u, axis=1, edge_order=1),
        np.gradient(unit_v, axis=1, edge_order=1),
    ) + 0.5 * np.hypot(
        np.gradient(unit_u, axis=0, edge_order=1),
        np.gradient(unit_v, axis=0, edge_order=1),
    )
    valid = np.isfinite(u) & np.isfinite(v)
    if context.support_mask is not None:
        valid &= np.asarray(context.support_mask, dtype=bool)
    score = (
        0.44 * _normalise_field(deformation, valid)
        + 0.30 * _normalise_field(direction_gradient, valid)
        + 0.16 * _normalise_field(convergence, valid)
        + 0.10 * _normalise_field(vorticity, valid)
    )
    if context.support_distance_km is not None:
        distance = np.asarray(context.support_distance_km, dtype=float)
        support = np.clip((850.0 - distance) / 650.0, 0.0, 1.0)
        score *= 0.65 + 0.35 * support
    return np.where(valid, score, 0.0)


def _sample_grid_mean(
    coordinates: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    field: np.ndarray,
) -> float:
    if coordinates.shape[0] == 0:
        return 0.0
    y_index = np.abs(lat[:, None] - coordinates[:, 1][None, :]).argmin(axis=0)
    x_index = np.abs(lon[:, None] - coordinates[:, 0][None, :]).argmin(axis=0)
    values = np.asarray(field, dtype=float)[y_index, x_index]
    values = values[np.isfinite(values)]
    return float(np.nanmean(values)) if values.size else 0.0


def _orient_like_original(segment: LineString, original: LineString) -> np.ndarray:
    coordinates = np.asarray(segment.coords, dtype=float)
    if coordinates.shape[0] < 2:
        return coordinates
    start = Point(coordinates[0])
    end = Point(coordinates[-1])
    original_start = Point(original.coords[0])
    if end.distance(original_start) < start.distance(original_start):
        coordinates = coordinates[::-1]
    return coordinates


def _snap_segment_contacts(
    coordinates: np.ndarray,
    trough_lines: list[tuple[str, LineString, float]],
) -> tuple[np.ndarray, list[str]]:
    values = np.asarray(coordinates, dtype=float).copy()
    related: set[str] = set()
    if values.shape[0] < 2:
        return values, []
    for endpoint_index in (0, -1):
        point = Point(values[endpoint_index])
        best: tuple[float, str, Point] | None = None
        for trough_id, trough, radius in trough_lines:
            nearest_on_point, nearest_on_trough = nearest_points(point, trough)
            distance = float(nearest_on_point.distance(nearest_on_trough))
            if distance > radius + 18.0:
                continue
            candidate = (distance, trough_id, nearest_on_trough)
            if best is None or candidate[0] < best[0]:
                best = candidate
        if best is not None:
            values[endpoint_index] = np.asarray(best[2].coords[0], dtype=float)
            related.add(best[1])
    return values, sorted(related)


def _crosses_any(coordinates: np.ndarray, trough_lines: list[tuple[str, LineString, float]]) -> bool:
    if coordinates.shape[0] < 2:
        return False
    line = LineString(coordinates)
    return any(line.crosses(trough) for _, trough, _ in trough_lines)


def resolve_trough_shear_topology(
    troughs: Iterable[dict[str, Any]],
    shears: Iterable[dict[str, Any]],
    *,
    z500: np.ndarray | None = None,
    u500: np.ndarray | None = None,
    v500: np.ndarray | None = None,
    lat: Iterable[float] | None = None,
    lon: Iterable[float] | None = None,
    support_distance_km: np.ndarray | None = None,
    support_mask: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Remove X-shaped trough/shear conflicts while keeping meaningful shears.

    Occasional endpoint contact is retained.  Interior crossings and long close
    overlaps are resolved with trough priority: the shear is clipped to the
    strongest contiguous side and terminates at the Z500 trough as a junction.
    """
    trough_items = [deepcopy(item) for item in troughs if _line_coordinates(item).shape[0] >= 2]
    shear_items = [deepcopy(item) for item in shears if _line_coordinates(item).shape[0] >= 2]
    if not trough_items or not shear_items:
        return shear_items

    context: _TopologyContext | None = None
    evidence: np.ndarray | None = None
    lat_values: np.ndarray | None = None
    lon_values: np.ndarray | None = None
    if all(value is not None for value in (z500, u500, v500, lat, lon)):
        lat_values = np.asarray(list(lat), dtype=float)
        lon_values = np.asarray(list(lon), dtype=float)
        context = _TopologyContext(
            troughs=tuple(trough_items),
            z500=np.asarray(z500, dtype=float),
            u500=np.asarray(u500, dtype=float),
            v500=np.asarray(v500, dtype=float),
            lat=lat_values,
            lon=lon_values,
            support_distance_km=(
                None if support_distance_km is None else np.asarray(support_distance_km, dtype=float)
            ),
            support_mask=(None if support_mask is None else np.asarray(support_mask, dtype=bool)),
        )
        evidence = _shear_evidence_field(context)

    output: list[dict[str, Any]] = []
    for system in shear_items:
        source_coordinates = _line_coordinates(system)
        reference_lat = float(np.nanmedian(source_coordinates[:, 1]))
        source_xy = _to_xy(source_coordinates, reference_lat)
        original_line = LineString(source_xy)
        if original_line.length <= 1.0e-6:
            continue

        conflict_lines: list[tuple[str, LineString, float]] = []
        buffers = []
        close_length_total = 0.0
        crossing_count = 0
        for index, trough_system in enumerate(trough_items, start=1):
            trough_coordinates = _line_coordinates(trough_system)
            trough_line = LineString(_to_xy(trough_coordinates, reference_lat))
            if trough_line.length <= 1.0e-6:
                continue
            radius = _trough_clearance_km(trough_system)
            trough_id = str(trough_system.get("id") or f"trough-{index}")
            nearest_shear, _ = nearest_points(original_line, trough_line)
            position = float(original_line.project(nearest_shear))
            endpoint_only = (
                not original_line.crosses(trough_line)
                and min(position, original_line.length - position) <= 70.0
            )
            buffered = trough_line.buffer(radius, cap_style=2, join_style=2)
            close_length = float(original_line.intersection(buffered).length)
            if endpoint_only and close_length <= radius * 1.3:
                continue
            if not original_line.crosses(trough_line) and close_length < 28.0:
                continue
            conflict_lines.append((trough_id, trough_line, radius))
            buffers.append(buffered)
            close_length_total += close_length
            crossing_count += int(original_line.crosses(trough_line))

        if not conflict_lines:
            output.append(system)
            continue

        outside = original_line.difference(unary_union(buffers))
        candidates = _geometry_lines(outside)
        minimum_length = max(260.0, min(420.0, original_line.length * 0.28))
        ranked: list[tuple[float, float, LineString, np.ndarray]] = []
        for segment in candidates:
            if segment.length < minimum_length:
                continue
            xy = _orient_like_original(segment, original_line)
            lonlat = _to_lonlat(xy, reference_lat)
            mean_evidence = 0.0
            if evidence is not None and lat_values is not None and lon_values is not None:
                mean_evidence = _sample_grid_mean(lonlat, lat_values, lon_values, evidence)
            rank = float(segment.length * (0.78 + 0.42 * mean_evidence))
            ranked.append((rank, mean_evidence, segment, xy))

        if not ranked:
            # The line is almost entirely a duplicate of a robust Z500 trough.
            continue

        _, mean_evidence, selected, selected_xy = max(ranked, key=lambda item: item[0])
        selected_xy, related_ids = _snap_segment_contacts(selected_xy, conflict_lines)
        if selected_xy.shape[0] < 2:
            continue
        selected_lonlat = _to_lonlat(selected_xy, reference_lat)
        if _crosses_any(selected_xy, conflict_lines):
            # Snapping should only create endpoint contact.  If numerical geometry
            # still creates a true crossing, keep the unsnapped outside segment.
            selected_xy = _orient_like_original(selected, original_line)
            selected_lonlat = _to_lonlat(selected_xy, reference_lat)
            related_ids = []
        if selected_lonlat.shape[0] < 2:
            continue

        geometry = dict(system.get("geometry") or {})
        geometry["coordinates"] = [
            [float(longitude), float(latitude)]
            for longitude, latitude in selected_lonlat
        ]
        system["geometry"] = geometry
        system["axis_length_km"] = round(float(selected.length), 1)
        system["topology_refinement_version"] = TOPOLOGY_REFINEMENT_VERSION
        system["topology_resolution"] = "terminate_shear_at_z500_trough"
        system["related_trough_ids"] = related_ids or [item[0] for item in conflict_lines]
        system["topology_metrics"] = {
            "crossing_count_before": int(crossing_count),
            "close_overlap_length_km": round(float(close_length_total), 1),
            "original_length_km": round(float(original_line.length), 1),
            "retained_length_km": round(float(selected.length), 1),
            "removed_length_km": round(float(max(0.0, original_line.length - selected.length)), 1),
            "retained_shear_evidence_mean": round(float(mean_evidence), 4),
        }
        evidence_list = list(system.get("evidence") or [])
        evidence_list.append(
            "同层Z500槽线优先：独立切变线在槽轴处终止或去除重叠段，避免不合理X形穿越"
        )
        system["evidence"] = evidence_list
        output.append(system)
    return output


def install_sounding_topology_refinements() -> None:
    """Patch the sounding detector/merge pair with request-local topology context."""
    from weather_diag.features import sounding_trough_paths as target

    if getattr(target, "_trough_shear_topology_v6_installed", False):
        return
    original_detect = target.detect_sounding_multitrack_troughs
    original_merge = target.merge_shear_systems

    def detect_with_topology_context(
        z500,
        u500,
        v500,
        lat,
        lon,
        *,
        support_distance_km=None,
        support_mask=None,
        confidence=0.72,
        config=None,
    ):
        systems = original_detect(
            z500,
            u500,
            v500,
            lat,
            lon,
            support_distance_km=support_distance_km,
            support_mask=support_mask,
            confidence=confidence,
            config=config,
        )
        _LAST_CONTEXT.set(
            _TopologyContext(
                troughs=tuple(deepcopy(systems)),
                z500=np.asarray(z500, dtype=float),
                u500=np.asarray(u500, dtype=float),
                v500=np.asarray(v500, dtype=float),
                lat=np.asarray(list(lat), dtype=float),
                lon=np.asarray(list(lon), dtype=float),
                support_distance_km=(
                    None
                    if support_distance_km is None
                    else np.asarray(support_distance_km, dtype=float)
                ),
                support_mask=(
                    None if support_mask is None else np.asarray(support_mask, dtype=bool)
                ),
            )
        )
        return systems

    def merge_with_topology(
        systems,
        supplement,
        *,
        duplicate_distance_km=180.0,
    ):
        merged = original_merge(
            systems,
            supplement,
            duplicate_distance_km=duplicate_distance_km,
        )
        context = _LAST_CONTEXT.get()
        _LAST_CONTEXT.set(None)
        if context is None:
            return merged
        try:
            return resolve_trough_shear_topology(
                context.troughs,
                merged,
                z500=context.z500,
                u500=context.u500,
                v500=context.v500,
                lat=context.lat,
                lon=context.lon,
                support_distance_km=context.support_distance_km,
                support_mask=context.support_mask,
            )
        except Exception:
            return merged

    detect_with_topology_context._sounding_topology_context_v6 = True
    merge_with_topology._sounding_topology_resolution_v6 = True
    target.detect_sounding_multitrack_troughs = detect_with_topology_context
    target.merge_shear_systems = merge_with_topology
    target._trough_shear_topology_v6_installed = True
