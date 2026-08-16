"""
A scheduled run that never gets as far as scraping a URL - missing bulk file, empty
file, or an unexpected error before parsing starts - must still leave a run history
record. Otherwise the answer to "did last night's run do anything" stays "check the
logs" for exactly the runs that did the least.
"""

import uuid
from unittest.mock import patch

import pytest

from artwork_uploader import process_bulk_file_on_schedule
from models.instance import Instance
from services.run_history import RunHistory
from core.enums import RunTrigger, RunOutcome
TRIGGER_SCHEDULED = RunTrigger.SCHEDULED.value
OUTCOME_FAILED = RunOutcome.FAILED.value
OUTCOME_SKIPPED = RunOutcome.SKIPPED.value


# A run counts as scheduled when it carries a schedule id. The value itself is
# not read by anything under test here, only its presence.
SCHEDULE_ID = str(uuid.uuid4())


@pytest.fixture
def history(tmp_path, monkeypatch):
    real_history = RunHistory(str(tmp_path / "run_history.json"))
    monkeypatch.setattr("artwork_uploader.RunHistory", lambda: real_history)
    return real_history


@pytest.mark.unit
def test_missing_bulk_file_is_recorded_as_failed(history):
    with patch("artwork_uploader.find_bulk_file", return_value=None):
        process_bulk_file_on_schedule(Instance(mode="cli"), "missing.txt", SCHEDULE_ID)

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["label"] == "missing.txt"
    assert runs[0]["outcome"] == OUTCOME_FAILED
    assert runs[0]["trigger"] == TRIGGER_SCHEDULED


@pytest.mark.unit
def test_empty_bulk_file_is_recorded_as_skipped(history, tmp_path):
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")

    with patch("artwork_uploader.find_bulk_file", return_value=str(empty_file)):
        process_bulk_file_on_schedule(Instance(mode="cli"), "empty.txt", SCHEDULE_ID)

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_SKIPPED


@pytest.mark.unit
def test_unexpected_failure_before_parsing_is_recorded(history):
    with patch("artwork_uploader.find_bulk_file", side_effect=RuntimeError("boom")):
        process_bulk_file_on_schedule(Instance(mode="cli"), "broken.txt", SCHEDULE_ID)

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_FAILED
