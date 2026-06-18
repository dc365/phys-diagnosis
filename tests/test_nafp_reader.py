from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from weather_diag.data.nafp import (
    NAFP_SAMPLE_ROOT,
    load_nafp_field,
    nafp_product_path,
    open_nafp_dataset,
)


RUN_TIME = datetime(2026, 6, 17, 20)


def test_nafp_product_path_formats_directory_layout():
    path = nafp_product_path(NAFP_SAMPLE_ROOT, "gh", "500", RUN_TIME, 24)

    assert path == Path(
        "/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NEW_NC/"
        "gh/500/2026/06/17/20/26061720.024"
    )


def test_open_nafp_dataset_reads_gzip_netcdf_without_gz_suffix():
    path = nafp_product_path(NAFP_SAMPLE_ROOT, "gh", "500", RUN_TIME, 24)

    ds = open_nafp_dataset(path)

    assert list(ds.sizes) == ["lat", "lon"]
    assert ds.sizes["lat"] == 241
    assert ds.sizes["lon"] == 361
    assert "gh" in ds.data_vars


def test_load_nafp_field_reads_multivariable_uv850():
    field = load_nafp_field(NAFP_SAMPLE_ROOT, "uv", "850", RUN_TIME, 24)

    assert field.key == "uv850"
    assert field.exists is True
    assert set(field.variables) == {"u", "v"}
    assert field.lat.shape == (241,)
    assert field.lon.shape == (361,)
    assert field.values["u"].shape == (241, 361)
    assert np.isfinite(field.values["u"]).any()
    assert field.source_path.endswith("uv/850/2026/06/17/20/26061720.024")


def test_load_nafp_field_marks_missing_optional_field():
    field = load_nafp_field(NAFP_SAMPLE_ROOT, "not_real", "999", RUN_TIME, 24, required=False)

    assert field.exists is False
    assert field.missing_reason == "not_found"
    assert field.values == {}
