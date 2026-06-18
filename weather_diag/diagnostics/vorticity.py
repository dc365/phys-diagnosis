from __future__ import annotations

import numpy as np
from .grid import derivatives_lonlat


def relative_vorticity(u: np.ndarray, v: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    _, dudy = derivatives_lonlat(u, lat, lon)
    dvdx, _ = derivatives_lonlat(v, lat, lon)
    return dvdx - dudy
