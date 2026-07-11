from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_FILE = ROOT / "tests/test_sounding_analysis.py"


OLD_TEST = '''def test_sounding_troughs_recover_the_weak_southern_china_valley_track():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)

    lower_axes = []
    for item in result["systems"]:
        if item["feature_type"] != "trough_candidate":
            continue
        coordinates = np.asarray(item["geometry"]["coordinates"], dtype=float)
        core = coordinates[
            (coordinates[:, 0] >= 102.0)
            & (coordinates[:, 0] <= 114.0)
            & (coordinates[:, 1] >= 22.0)
            & (coordinates[:, 1] <= 36.0)
        ]
        if len(core) >= 2 and float(np.ptp(core[:, 1])) >= 4.0:
            lower_axes.append(item)

    assert lower_axes
    assert any(item["candidate_source"] == "meridional_valley_track" for item in lower_axes)
'''

NEW_TEST = '''def test_sounding_troughs_recover_the_hainan_valley_track():
    diagnose_sounding_situation = _diagnose_sounding_situation()
    result = diagnose_sounding_situation(SOUNDING_FILE, pressure_level=500)

    hainan_axes = []
    for item in result["systems"]:
        if item["feature_type"] != "trough_candidate":
            continue
        coordinates = np.asarray(item["geometry"]["coordinates"], dtype=float)
        core = coordinates[
            (coordinates[:, 0] >= 105.0)
            & (coordinates[:, 0] <= 114.0)
            & (coordinates[:, 1] >= 13.0)
            & (coordinates[:, 1] <= 21.0)
        ]
        if len(core) >= 2 and float(np.ptp(core[:, 1])) >= 3.0:
            hainan_axes.append(item)

    assert hainan_axes
    assert any(
        item["candidate_source"] == "meridional_valley_track"
        and item.get("supplement_region") == "south_china_hainan"
        for item in hainan_axes
    )
'''


def main() -> None:
    text = TEST_FILE.read_text(encoding="utf-8")
    changed = False

    adaptive_assertion = (
        '    assert z500["quality"]["analysis_version"] == "sounding_z500_synoptic_v2"\n'
        '    assert z500["quality"]["adaptive_analysis_version"] == "sounding_z500_synoptic_v3"\n'
        '    assert z500["quality"]["adaptive_station_only"] is True\n'
    )
    old_assertion = (
        '    assert z500["quality"]["analysis_version"] == "sounding_z500_synoptic_v2"\n'
    )
    if "adaptive_analysis_version" not in text:
        if old_assertion not in text:
            raise RuntimeError("analysis version assertion was not found")
        text = text.replace(old_assertion, adaptive_assertion, 1)
        changed = True

    if OLD_TEST in text:
        text = text.replace(OLD_TEST, NEW_TEST, 1)
        changed = True
    elif "test_sounding_troughs_recover_the_hainan_valley_track" not in text:
        raise RuntimeError("legacy southern trough regression block was not found")

    if changed:
        TEST_FILE.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
