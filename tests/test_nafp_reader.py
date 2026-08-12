from __future__ import annotations

import importlib
from datetime import datetime
from pathlib import Path

import numpy as np
import xarray as xr

from weather_diag.data import nafp as nafp_module
from weather_diag.data.nafp import (
    NAFP_SAMPLE_ROOT,
    load_nafp_field,
    nafp_product_path,
    open_nafp_dataset,
)


RUN_TIME = datetime(2026, 6, 17, 20)
CONFIGURED_NAFP_ROOT = Path("/Users/dc/Downloads/workspace/data/Weather/NAFP/NAFP_ECTHIN_NC")


def test_sample_root_uses_configured_absolute_path_even_when_env_is_set(monkeypatch):
    monkeypatch.setenv("WEATHER_DIAG_NAFP_ROOT", "/tmp/not-configured")
    monkeypatch.setenv("NAFP_ROOT", "/tmp/not-configured")

    import weather_diag.data.nafp as nafp_module

    assert importlib.reload(nafp_module).NAFP_SAMPLE_ROOT == CONFIGURED_NAFP_ROOT


def test_nafp_product_path_formats_directory_layout():
    path = nafp_product_path(NAFP_SAMPLE_ROOT, "gh", "500", RUN_TIME, 24)

    assert path == CONFIGURED_NAFP_ROOT / "gh/500/2026/06/17/20/26061720.024"


def test_open_nafp_dataset_reads_gzip_netcdf_without_gz_suffix():
    path = nafp_product_path(NAFP_SAMPLE_ROOT, "gh", "500", RUN_TIME, 24)

    ds = open_nafp_dataset(path)

    assert list(ds.sizes) == ["lat", "lon"]
    assert ds.sizes["lat"] == 241
    assert ds.sizes["lon"] == 361
    assert "gh" in ds.data_vars


def test_open_nafp_dataset_closes_backend_and_uses_configured_engine(monkeypatch, tmp_path):
    path = tmp_path / "26061720.024"
    path.write_bytes(b"CDF\x01test")
    closed = []
    opened_with = []
    source = xr.Dataset(
        {"gh": (("lat", "lon"), np.asarray([[588.0]]))},
        coords={"lat": [30.0], "lon": [110.0]},
    )
    source.set_close(lambda: closed.append(True))

    def fake_open_dataset(opened_path, **kwargs):
        opened_with.append((str(opened_path), kwargs))
        return source

    monkeypatch.setattr(nafp_module.xr, "open_dataset", fake_open_dataset)
    monkeypatch.delenv("WEATHER_DIAG_NAFP_NETCDF_ENGINE", raising=False)

    loaded = nafp_module.open_nafp_dataset(path)

    assert float(loaded["gh"].values[0, 0]) == 588.0
    assert closed == [True]
    assert opened_with[0][1]["engine"] == "netcdf4"


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


def test_load_nafp_field_masks_declared_missing_values():
    field = load_nafp_field(NAFP_SAMPLE_ROOT, "kindex", "999", RUN_TIME, 24)

    assert np.isnan(field.values["kindex"]).any()
    assert float(np.nanmax(field.values["kindex"])) < 100.0


def test_load_nafp_field_marks_missing_optional_field():
    field = load_nafp_field(NAFP_SAMPLE_ROOT, "not_real", "999", RUN_TIME, 24, required=False)

    assert field.exists is False
    assert field.missing_reason == "not_found"
    assert field.values == {}
