"""
A scheduled run that never gets as far as scraping a URL - missing bulk file, empty
file, or an unexpected error before parsing starts - must still leave a run history
record. Otherwise the answer to "did last night's run do anything" stays "check the
logs" for exactly the runs that did the least.
"""

from unittest.mock import MagicMock, patch

import pytest

import core.globals as globals
from artwork_uploader import process_bulk_file_on_schedule
from models.instance import Instance
from services.run_history import RunHistory, OUTCOME_FAILED, OUTCOME_SKIPPED


@pytest.fixture(autouse=True)
def scheduler_service():
    # The overlap guard merged from issue 8 releases the scheduler service in a
    # finally block, so these direct calls need a service present.
    with patch.object(globals, "scheduler_service", MagicMock()) as service:
        yield service


@pytest.fixture
def history(tmp_path, monkeypatch):
    real_history = RunHistory(str(tmp_path / "run_history.json"))
    monkeypatch.setattr("artwork_uploader.RunHistory", lambda: real_history)
    return real_history


@pytest.mark.unit
def test_missing_bulk_file_is_recorded_as_failed(history):
    with patch("artwork_uploader.find_bulk_file", return_value=None):
        process_bulk_file_on_schedule(Instance(mode="cli"), "missing.txt")

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["filename"] == "missing.txt"
    assert runs[0]["outcome"] == OUTCOME_FAILED
    assert runs[0]["scheduled"] is True


@pytest.mark.unit
def test_empty_bulk_file_is_recorded_as_skipped(history, tmp_path):
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")

    with patch("artwork_uploader.find_bulk_file", return_value=str(empty_file)):
        process_bulk_file_on_schedule(Instance(mode="cli"), "empty.txt")

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_SKIPPED


@pytest.mark.unit
def test_unexpected_failure_before_parsing_is_recorded(history):
    with patch("artwork_uploader.find_bulk_file", side_effect=RuntimeError("boom")):
        process_bulk_file_on_schedule(Instance(mode="cli"), "broken.txt")

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_FAILED
