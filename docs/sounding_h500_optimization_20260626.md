# Sounding H500 objective-analysis optimization

This update changes the public sounding analysis path from a quick triangulated field to a weather-chart-oriented objective analysis workflow.

## Why this changed

The first implementation used `griddata(linear) + nearest fill`. That is useful for a demo but it creates hard triangles, fake support over station-sparse areas, and noisy H500 contours. It is not suitable for comparison with an operational 500hPa weather chart.

The current `sounding_z500_synoptic_v2` path uses a multiscale Barnes-style
successive-correction objective analysis:

```text
profile rows
  -> log-pressure interpolation to exact 500hPa
  -> robust quadratic station-trend first guess
  -> 900/650/450km great-circle correction passes
  -> damped fine correction and synoptic smoothing
  -> 850km observation-support mask
```

The correction gains are `1.0/0.85/0.55`. The final pass therefore restores
supported trough curvature without forcing every station increment into the
synoptic field. Distances use a haversine great-circle metric; the old
single-reference-latitude planar approximation is no longer used.

When a first-guess background is supplied, all three correction radii are now
applied. Previously the broadest correction was accidentally skipped. Values
farther than 850 km from the nearest station are retained internally for
diagnostics but masked from the public Z500 grid and contours.

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
- `quality.analysis_version = sounding_z500_synoptic_v2`
- `quality.distance_method = great_circle_haversine`
- `quality.correction_radii_km` and `quality.correction_gains`
- exact/interpolated 500hPa station counts

The public API metadata exposes support ratio, mean nearest-station distance, and station residual RMSE.

## Added map layers

The sounding layer API now supports:

- `z500`: 500hPa height, displayed as dagpm
- `t500`: 500hPa temperature, displayed as degC

Z500 uses supported-area masking before generating grids or contours. Its
contour endpoint does not smooth the scalar field a second time, so contours,
height centres, and trough/ridge extraction all reference the same canonical
`analysis_fields.z500` field. Geometric Chaikin smoothing remains enabled only
for drawing a clean line.

## NMC-style contour support

`weather_diag/io/contours.py` now supports:

- minimum contour segment length filtering
- light Chaikin smoothing
- contour metadata including `line_color`, `line_width`, `line_dash`, `label_color`
- z500 blue contour style
- t500 red contour style, with negative contours marked dashed in metadata

## Weather systems

The optimized wrapper regenerates H/L/W/C and trough/ridge systems from the
canonical Z500 field. Sounding trough/ridge axes are rejected when their mean
or upper-tail nearest-station distance indicates weak observational support.
It also adds a 500hPa wind-shear line pass so station-derived systems can
distinguish height trough axes from wind-shear support.

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
