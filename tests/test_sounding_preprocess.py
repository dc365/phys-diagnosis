from pathlib import Path

from weather_diag.diagnosis import sounding_preprocess as sp


def test_preprocess_status_returns_state_updated_at_as_iso_text(monkeypatch, tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("station_id\n", encoding="utf-8")
    state_path = tmp_path / "state.json"
    state_path.write_text('{"updated_at": "2026-06-29T03:00:00+00:00"}', encoding="utf-8")

    monkeypatch.setattr(sp, "STATE_PATH", state_path)
    monkeypatch.setattr(sp, "discover_sounding_csvs", lambda root=None: [csv_path])
    monkeypatch.setattr(sp, "_reports", lambda: [])

    result = sp.preprocess_status(root=tmp_path)

    assert result["updated_at"] == "2026-06-29T03:00:00+00:00"
    assert isinstance(result["updated_at"], str)


def test_autostart_sounding_preprocess_queues_pending_files(monkeypatch, tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("station_id\n", encoding="utf-8")
    calls = []

    class InlineThread:
        def __init__(self, *, target, name, daemon):
            self.target = target

        def is_alive(self):
            return False

        def start(self):
            self.target()

    monkeypatch.setattr(sp, "_AUTO_PREPROCESS_THREAD", None)
    monkeypatch.setattr(sp, "discover_sounding_csvs", lambda root=None: [csv_path])
    monkeypatch.setattr(sp, "report_path_for", lambda path: Path(tmp_path / "missing.preprocess.json"))
    monkeypatch.setattr(sp, "cleaned_path_for", lambda path: Path(tmp_path / "missing.clean.csv"))
    monkeypatch.setattr(sp, "run_preprocess", lambda **kwargs: calls.append(kwargs) or {"processed_count": 1})
    monkeypatch.setattr(sp.threading, "Thread", InlineThread)

    result = sp.autostart_sounding_preprocess(root=tmp_path)

    assert result == {"status": "queued", "pending_count": 1}
    assert calls == [{"root": tmp_path, "force": False}]
