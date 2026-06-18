from __future__ import annotations

import numpy as np
from .grid import derivatives_lonlat


def scalar_advection(u: np.ndarray, v: np.ndarray, scalar: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    dsdx, dsdy = derivatives_lonlat(scalar, lat, lon)
    return -1.0 * (u * dsdx + v * dsdy)
