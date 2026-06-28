# Sounding H500 CMA/NMC tuning patch

This package contains two replacement files:

- `weather_diag/diagnosis/sounding_optimized.py`
- `backend/app/api/v1/sounding.py`

Purpose:

1. Remove unrealistic northern dense z500 contour nests by adding a 500hPa height QC step and a robust polynomial first-guess field before Barnes objective analysis.
2. Preserve the southern/subtropical 588-dagpm contour near South China/Hainan by using a background + station-increment analysis and lowering the z500 contour minimum length filter from 520 km to 360 km.
3. Keep NMC-style contour smoothing, but avoid over-filtering meaningful 588-dagpm arcs.

Apply:

```bash
cp weather_diag/diagnosis/sounding_optimized.py <repo>/weather_diag/diagnosis/sounding_optimized.py
cp backend/app/api/v1/sounding.py <repo>/backend/app/api/v1/sounding.py

python -m py_compile \
  weather_diag/diagnosis/sounding_optimized.py \
  backend/app/api/v1/sounding.py

pytest -q tests/test_sounding_analysis.py
```

Suggested visual check:

- `phy_sounding_2026062520.jpg`
- `SEVP_NMC_WESA_SFER_EGH_ACWP_L50_P9_20260625120000000.jpeg`

Expected improvements:

- The northern artificial tight 516/532-dagpm closed center should be strongly reduced or removed.
- The southern 588-dagpm contour around South China/Hainan should be easier to retain.
