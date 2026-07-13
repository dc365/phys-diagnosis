"""Weather situation diagnosis orchestration.

The public sounding path imports :mod:`weather_diag.diagnosis.objective_analysis`
through this package.  Install narrowly scoped sounding wrappers here so the
primary 500hPa height analysis can use the station-only adaptive method and its
weather-system geometry can be refined without changing model-grid or other
pressure-level objective analyses.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from . import objective_analysis as _objective_analysis
from .sounding_z500_adaptive import (
    ADAPTIVE_Z500_VERSION,
    adaptive_station_z500,
)


class _AdaptiveQuality(dict):
    """Preserve adaptive metadata when the legacy wrapper adds contract fields."""

    def update(self, *args, **kwargs) -> None:  # type: ignore[override]
        incoming: dict[str, Any] = {}
        for mapping in args:
            incoming.update(dict(mapping))
        incoming.update(kwargs)
        incoming.update(
            {
                "background_used": True,
                "background_method": "station_only_adaptive_multiscale",
                "adaptive_station_only": True,
                "adaptive_analysis_version": ADAPTIVE_Z500_VERSION,
            }
        )
        super().update(incoming)


def _is_primary_sounding_z500(
    value_column: str,
    config,
    background,
) -> bool:
    if value_column != "geopotential_height_m" or background is None or config is None:
        return False
    radii = tuple(float(item) for item in getattr(config, "radii_km", ()) or ())
    gains = tuple(float(item) for item in getattr(config, "correction_gains", ()) or ())
    return (
        radii == (900.0, 650.0, 450.0)
        and gains == (1.0, 0.85, 0.55)
        and np.isclose(float(getattr(config, "smoothing_sigma_grid", 0.0)), 1.0)
        and np.isclose(float(getattr(config, "max_support_distance_km", 0.0)), 850.0)
    )


if not getattr(_objective_analysis.objective_analysis_field, "_sounding_z500_v3_wrapper", False):
    _original_objective_analysis_field = _objective_analysis.objective_analysis_field

    def _objective_analysis_with_adaptive_sounding_z500(
        frame,
        value_column,
        lat,
        lon,
        *,
        config=None,
        background=None,
    ):
        baseline = _original_objective_analysis_field(
            frame,
            value_column,
            lat,
            lon,
            config=config,
            background=background,
        )
        if not _is_primary_sounding_z500(value_column, config, background):
            return baseline

        adaptive = adaptive_station_z500(
            frame,
            np.asarray(list(lat), dtype=float),
            np.asarray(list(lon), dtype=float),
            baseline,
        )
        quality = _AdaptiveQuality(adaptive.quality)
        quality.update(
            {
                # Keep the existing public contract value until all external
                # consumers have moved to adaptive_analysis_version.
                "analysis_version": "sounding_z500_synoptic_v2",
                "field_role": "synoptic_z500",
            }
        )
        adaptive.quality = quality
        return adaptive

    _objective_analysis_with_adaptive_sounding_z500._sounding_z500_v3_wrapper = True
    _objective_analysis.objective_analysis_field = _objective_analysis_with_adaptive_sounding_z500


# ``sounding_optimized`` imports the geometry functions directly after the
# diagnosis package is initialised.  Install the contour-guided geometry patch
# first, then the trough/shear topology patch so the latter wraps the final
# smoothed functions.  Model/NAFP paths remain untouched.
try:
    from weather_diag.features.sounding_geometry_refine import (
        install_sounding_geometry_refinements,
    )

    install_sounding_geometry_refinements()
except Exception:
    pass

try:
    from weather_diag.features.sounding_topology_refine import (
        install_sounding_topology_refinements,
    )

    install_sounding_topology_refinements()
except Exception:
    pass
