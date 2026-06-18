from __future__ import annotations

import numpy as np


def wind_speed(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    return np.sqrt(np.asarray(u, dtype=float) ** 2 + np.asarray(v, dtype=float) ** 2)


def wind_direction_from(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Meteorological wind direction in degrees: direction FROM which wind blows."""
    return (270.0 - np.rad2deg(np.arctan2(v, u))) % 360.0
