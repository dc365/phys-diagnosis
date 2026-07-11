from __future__ import annotations

from pathlib import Path


DATA_DIR = Path(
    "test_datas/regional_radiosonde_5N55N_50E160E_20260624_20260625"
)


def test_four_reference_sounding_cycles_are_available():
    expected = {
        "regional_radiosonde_5N55N_50E160E_20260624_08BJT.csv",
        "regional_radiosonde_5N55N_50E160E_20260624_20BJT.csv",
        "regional_radiosonde_5N55N_50E160E_20260625_08BJT.csv",
        "regional_radiosonde_5N55N_50E160E_20260625_20BJT.csv",
    }
    assert expected <= {path.name for path in DATA_DIR.glob("regional_radiosonde*.csv")}
