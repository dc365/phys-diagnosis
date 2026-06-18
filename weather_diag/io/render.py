from __future__ import annotations

import io
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def render_png(data, lat, lon, *, title: str = "", unit: str = "", cmap: str = "viridis", dpi: int = 120) -> bytes:
    arr = np.asarray(data, dtype=float)
    fig, ax = plt.subplots(figsize=(9, 5), dpi=dpi)
    lon2, lat2 = np.meshgrid(lon, lat)
    # Robust color bounds.
    valid = arr[np.isfinite(arr)]
    if valid.size:
        vmin, vmax = np.nanpercentile(valid, [2, 98])
        if abs(vmax - vmin) < 1e-12:
            vmin, vmax = float(np.nanmin(valid)), float(np.nanmax(valid) + 1e-6)
    else:
        vmin, vmax = 0, 1
    mesh = ax.pcolormesh(lon2, lat2, arr, shading="auto", cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(title)
    ax.grid(True, linewidth=0.3, alpha=0.4)
    cb = fig.colorbar(mesh, ax=ax, shrink=0.85)
    if unit:
        cb.set_label(unit)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
