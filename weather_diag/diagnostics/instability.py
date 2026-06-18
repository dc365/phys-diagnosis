from __future__ import annotations

import numpy as np
from .moisture import dewpoint_from_rh
from .wind import wind_speed


def k_index(t850_c, t700_c, t500_c, rh850=None, rh700=None, td850_c=None, td700_c=None):
    """K = (T850 - T500) + Td850 - (T700 - Td700)."""
    if td850_c is None:
        if rh850 is None:
            raise ValueError("K index requires td850_c or rh850")
        td850_c = dewpoint_from_rh(t850_c, rh850)
    if td700_c is None:
        if rh700 is None:
            raise ValueError("K index requires td700_c or rh700")
        td700_c = dewpoint_from_rh(t700_c, rh700)
    return (t850_c - t500_c) + td850_c - (t700_c - td700_c)


def deep_layer_shear(u_low, v_low, u_high, v_high):
    return wind_speed(u_high - u_low, v_high - v_low)
