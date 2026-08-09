"""Unit tests for the persistent bulk-import run history (services/run_history.py)."""

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from services.run_history import (
    RunHistory,
    OUTCOME_SUCCESS,
    OUTCOME_PARTIAL,
    OUTCOME_STOPPED,
    OUTCOME_FAILED,
    OUTCOME_SKIPPED,
)


def _iso(offset_days=0):
    return (datetime.now(timezone.utc) - timedelta(days=offset_days)).isoformat()


@pytest.fixture
def history(tmp_path):
    return RunHistory(str(tmp_path / "run_history.json"))


@pytest.mark.unit
def test_add_run_persists_the_record(history):
    history.add_run(
        "bulk_import.txt", _iso(), _iso(), scheduled=True, outcome=OUTCOME_SUCCESS,
        assets_processed=5, success_count=4, cached_count=1, locked_count=0, error_count=0
    )

    runs = history.get_runs()

    assert len(runs) == 1
    run = runs[0]
    assert run["filename"] == "bulk_import.txt"
    assert run["scheduled"] is True
    assert run["outcome"] == OUTCOME_SUCCESS
    assert run["assets_processed"] == 5
    assert run["success_count"] == 4
    assert run["cached_count"] == 1
    assert run["locked_count"] == 0
    assert run["error_count"] == 0


@pytest.mark.unit
def test_get_runs_returns_most_recent_first(history):
    history.add_run("first.txt", _iso(2), _iso(2), False, OUTCOME_SUCCESS)
    history.add_run("second.txt", _iso(1), _iso(1), False, OUTCOME_SUCCESS)
    history.add_run("third.txt", _iso(0), _iso(0), False, OUTCOME_SUCCESS)

    filenames = [run["filename"] for run in history.get_runs()]

    assert filenames == ["third.txt", "second.txt", "first.txt"]


@pytest.mark.unit
def test_get_runs_respects_limit(history):
    for n in range(5):
        history.add_run(f"file{n}.txt", _iso(), _iso(), False, OUTCOME_SUCCESS)

    assert len(history.get_runs(limit=2)) == 2


@pytest.mark.unit
def test_records_every_outcome(history):
    for outcome in (OUTCOME_SUCCESS, OUTCOME_PARTIAL, OUTCOME_STOPPED, OUTCOME_FAILED, OUTCOME_SKIPPED):
        history.add_run("bulk_import.txt", _iso(), _iso(), False, outcome)

    outcomes = {run["outcome"] for run in history.get_runs()}

    assert outcomes == {OUTCOME_SUCCESS, OUTCOME_PARTIAL, OUTCOME_STOPPED, OUTCOME_FAILED, OUTCOME_SKIPPED}


@pytest.mark.unit
def test_prunes_by_entry_count(tmp_path):
    history = RunHistory(str(tmp_path / "run_history.json"), max_entries=3, max_age_days=0)

    for n in range(5):
        history.add_run(f"file{n}.txt", _iso(), _iso(), False, OUTCOME_SUCCESS)

    runs = history.get_runs()

    assert len(runs) == 3
    assert [run["filename"] for run in runs] == ["file4.txt", "file3.txt", "file2.txt"]


@pytest.mark.unit
def test_prunes_by_age(tmp_path):
    history = RunHistory(str(tmp_path / "run_history.json"), max_entries=0, max_age_days=30)

    history.add_run("old.txt", _iso(60), _iso(60), False, OUTCOME_SUCCESS)
    history.add_run("recent.txt", _iso(1), _iso(1), False, OUTCOME_SUCCESS)

    filenames = [run["filename"] for run in history.get_runs()]

    assert filenames == ["recent.txt"]


@pytest.mark.unit
def test_survives_across_instances(tmp_path):
    path = str(tmp_path / "run_history.json")
    RunHistory(path).add_run("bulk_import.txt", _iso(), _iso(), False, OUTCOME_SUCCESS)

    assert len(RunHistory(path).get_runs()) == 1


@pytest.mark.unit
def test_get_runs_on_missing_file_returns_empty_list(tmp_path):
    history = RunHistory(str(tmp_path / "does_not_exist.json"))

    assert history.get_runs() == []


@pytest.mark.unit
def test_self_heals_from_a_corrupted_file(tmp_path):
    path = tmp_path / "run_history.json"
    path.write_text("not valid json", encoding="utf-8")

    history = RunHistory(str(path))
    history.add_run("bulk_import.txt", _iso(), _iso(), False, OUTCOME_SUCCESS)

    assert len(history.get_runs()) == 1
    assert json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.unit
def test_concurrent_runs_finishing_together_do_not_lose_a_record(tmp_path):
    """A scheduled run landing at the same moment as a manual one must not have one
    read-modify-write clobber the other's record - see the schedules a day can carry."""
    path = str(tmp_path / "run_history.json")

    def add(n):
        RunHistory(path).add_run(f"file{n}.txt", _iso(), _iso(), False, OUTCOME_SUCCESS)

    threads = [threading.Thread(target=add, args=(n,)) for n in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(RunHistory(path).get_runs()) == 20
