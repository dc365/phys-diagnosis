from __future__ import annotations

import numpy as np
from .grid import derivatives_lonlat


def moisture_flux(u: np.ndarray, v: np.ndarray, q: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    # q may be kg/kg or g/kg; the magnitude remains a relative indicator if configured consistently.
    fu = q * u
    fv = q * v
    mag = np.sqrt(fu ** 2 + fv ** 2)
    return fu, fv, mag


def moisture_flux_divergence(fu: np.ndarray, fv: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    dfudx, _ = derivatives_lonlat(fu, lat, lon)
    _, dfvdy = derivatives_lonlat(fv, lat, lon)
    return dfudx + dfvdy


def moisture_convergence(fu: np.ndarray, fv: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    return -moisture_flux_divergence(fu, fv, lat, lon)


def dewpoint_from_rh(temp_c: np.ndarray, rh_percent: np.ndarray) -> np.ndarray:
    """Magnus approximation for dewpoint from temperature Celsius and RH percent."""
    t = np.asarray(temp_c, dtype=float)
    rh = np.clip(np.asarray(rh_percent, dtype=float), 1e-3, 100.0)
    a, b = 17.625, 243.04
    gamma = np.log(rh / 100.0) + (a * t) / (b + t)
    return (b * gamma) / (a - gamma)
