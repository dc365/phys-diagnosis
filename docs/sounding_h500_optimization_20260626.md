# Sounding H500 objective-analysis optimization

This update changes the public sounding analysis path from a quick triangulated field to a weather-chart-oriented objective analysis workflow.

## Why this changed

The first implementation used `griddata(linear) + nearest fill`. That is useful for a demo but it creates hard triangles, fake support over station-sparse areas, and noisy H500 contours. It is not suitable for comparison with an operational 500hPa weather chart.

The new path uses a Barnes-style successive-correction objective analysis:

```text
station values
  -> broad first pass
  -> medium correction pass
  -> fine correction pass
  -> light smoothing
  -> support-distance mask
```

Default radii are 720/480/300 km. Values farther than 520 km from the nearest station are masked for map layers and contours.

## Runtime path

The sounding API now imports:

```text
weather_diag.diagnosis.sounding_optimized.diagnose_sounding_situation
```

The legacy `weather_diag.diagnosis.sounding` module remains available, but the public API uses the optimized wrapper.

## Added fields and quality metadata

Each sounding analysis field now includes:

- `support_distance_km`
- `support_mask`
- `quality.method = barnes_successive_correction`
- `quality.supported_grid_ratio`
- `quality.station_residual_rmse`
- `quality.station_residual_abs_p90`

The public API metadata exposes support ratio, mean nearest-station distance, and station residual RMSE.

## Added map layers

The sounding layer API now supports:

- `z500`: 500hPa height, displayed as dagpm
- `t500`: 500hPa temperature, displayed as degC

Both layers use supported-area masking before generating grids or contours.

## NMC-style contour support

`weather_diag/io/contours.py` now supports:

- minimum contour segment length filtering
- light Chaikin smoothing
- contour metadata including `line_color`, `line_width`, `line_dash`, `label_color`
- z500 blue contour style
- t500 red contour style, with negative contours marked dashed in metadata

## Weather systems

The optimized wrapper regenerates H/L/W/C and trough/ridge systems from the Barnes field. It also adds a 500hPa wind-shear line pass so station-derived systems can distinguish height trough axes from wind-shear support.

## Remaining front-end work

The API supports `t500`, but the current MapLibre page still defaults sounding analysis to `z500`. The next UI step is to expose a small sounding-layer selector with:

- z500 height field
- t500 temperature field
- station wind plot
- z500 + t500 dual-contour overlay

## Recommended validation

Use the four files under `test_datas/regional_radiosonde_5N55N_50E160E_20260624_20260625` and compare against the same-time NMC H500 chart by checking:

- z500 contour fragmentation count
- z500 main contour displacement
- H/L/W/C center displacement
- trough-axis length and tilt error
- unsupported-contour ratio
- station residual RMSE
