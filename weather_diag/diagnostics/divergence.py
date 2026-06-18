from __future__ import annotations

import numpy as np
from .grid import derivatives_lonlat


def divergence(u: np.ndarray, v: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    dudx, _ = derivatives_lonlat(u, lat, lon)
    _, dvdy = derivatives_lonlat(v, lat, lon)
    return dudx + dvdy


def convergence(u: np.ndarray, v: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    return -divergence(u, v, lat, lon)
