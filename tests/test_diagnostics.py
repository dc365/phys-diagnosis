import numpy as np

from weather_diag.diagnostics.wind import wind_speed, wind_direction_from
from weather_diag.diagnostics.divergence import divergence
from weather_diag.diagnostics.vorticity import relative_vorticity


def test_wind_speed_direction():
    u = np.array([[1.0, 0.0]])
    v = np.array([[0.0, 1.0]])
    assert np.allclose(wind_speed(u, v), [[1.0, 1.0]])
    # u>0 is wind blowing eastward, so it comes from west, around 270 deg.
    assert np.allclose(wind_direction_from(u, v)[0, 0], 270.0)


def test_divergence_vorticity_shapes():
    lat = np.linspace(20, 30, 6)
    lon = np.linspace(100, 110, 7)
    LON, LAT = np.meshgrid(lon, lat)
    u = LON * 0 + 5
    v = LAT * 0 + 2
    div = divergence(u, v, lat, lon)
    vort = relative_vorticity(u, v, lat, lon)
    assert div.shape == u.shape
    assert vort.shape == u.shape
    assert np.nanmax(np.abs(div)) < 1e-8
    assert np.nanmax(np.abs(vort)) < 1e-8
