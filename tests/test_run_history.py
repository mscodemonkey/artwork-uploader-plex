"""Unit tests for the persistent run history (services/run_history.py)."""

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from services.run_history import RunHistory
from core.enums import RunType, RunTrigger, RunOutcome

OUTCOME_SUCCESS = RunOutcome.SUCCESS.value
OUTCOME_PARTIAL = RunOutcome.PARTIAL.value
OUTCOME_STOPPED = RunOutcome.STOPPED.value
OUTCOME_FAILED = RunOutcome.FAILED.value
OUTCOME_SKIPPED = RunOutcome.SKIPPED.value
RUN_TYPE_BULK = RunType.BULK.value
RUN_TYPE_SCRAPE = RunType.SCRAPE.value
RUN_TYPE_UPLOAD = RunType.UPLOAD.value
RUN_TYPE_WEBHOOK = RunType.WEBHOOK.value
TRIGGER_MANUAL = RunTrigger.MANUAL.value
TRIGGER_SCHEDULED = RunTrigger.SCHEDULED.value
TRIGGER_RADARR = RunTrigger.RADARR.value



def _iso(offset_days=0):
    return (datetime.now(timezone.utc) - timedelta(days=offset_days)).isoformat()


@pytest.fixture
def history(tmp_path):
    return RunHistory(str(tmp_path / "run_history.json"))


@pytest.mark.unit
def test_add_run_persists_the_record(history):
    history.add_run(
        RUN_TYPE_BULK, "bulk_import.txt", _iso(), _iso(), trigger=TRIGGER_SCHEDULED, outcome=OUTCOME_SUCCESS,
        assets_processed=5, success_count=4, cached_count=1, locked_count=0, error_count=0
    )

    runs = history.get_runs()

    assert len(runs) == 1
    run = runs[0]
    assert run["run_type"] == RUN_TYPE_BULK
    assert run["label"] == "bulk_import.txt"
    assert run["trigger"] == TRIGGER_SCHEDULED
    assert run["outcome"] == OUTCOME_SUCCESS
    assert run["assets_processed"] == 5
    assert run["success_count"] == 4
    assert run["cached_count"] == 1
    assert run["locked_count"] == 0
    assert run["error_count"] == 0


@pytest.mark.unit
def test_get_runs_returns_most_recent_first(history):
    history.add_run(RUN_TYPE_BULK, "first.txt", _iso(2), _iso(2), TRIGGER_MANUAL, OUTCOME_SUCCESS)
    history.add_run(RUN_TYPE_BULK, "second.txt", _iso(1), _iso(1), TRIGGER_MANUAL, OUTCOME_SUCCESS)
    history.add_run(RUN_TYPE_BULK, "third.txt", _iso(0), _iso(0), TRIGGER_MANUAL, OUTCOME_SUCCESS)

    labels = [run["label"] for run in history.get_runs()]

    assert labels == ["third.txt", "second.txt", "first.txt"]


@pytest.mark.unit
def test_get_runs_respects_limit(history):
    for n in range(5):
        history.add_run(RUN_TYPE_BULK, f"file{n}.txt", _iso(), _iso(), TRIGGER_MANUAL, OUTCOME_SUCCESS)

    assert len(history.get_runs(limit=2)) == 2


@pytest.mark.unit
def test_records_every_run_type(history):
    for run_type in (RUN_TYPE_BULK, RUN_TYPE_SCRAPE, RUN_TYPE_UPLOAD, RUN_TYPE_WEBHOOK):
        history.add_run(run_type, f"{run_type} run", _iso(), _iso(), TRIGGER_MANUAL, OUTCOME_SUCCESS)

    run_types = {run["run_type"] for run in history.get_runs()}

    assert run_types == {RUN_TYPE_BULK, RUN_TYPE_SCRAPE, RUN_TYPE_UPLOAD, RUN_TYPE_WEBHOOK}


@pytest.mark.unit
def test_get_runs_filters_by_run_type(history):
    history.add_run(RUN_TYPE_BULK, "nightly.txt", _iso(3), _iso(3), TRIGGER_SCHEDULED, OUTCOME_SUCCESS)
    history.add_run(RUN_TYPE_WEBHOOK, "The Matrix (1999)", _iso(2), _iso(2), TRIGGER_RADARR, OUTCOME_SUCCESS)
    history.add_run(RUN_TYPE_SCRAPE, "https://theposterdb.com/set/1", _iso(1), _iso(1), TRIGGER_MANUAL, OUTCOME_SUCCESS)

    webhook_runs = history.get_runs(run_type=RUN_TYPE_WEBHOOK)

    assert [run["label"] for run in webhook_runs] == ["The Matrix (1999)"]


@pytest.mark.unit
def test_the_type_filter_is_applied_before_the_limit(history):
    """Asking for bulk imports must return the last N bulk imports, not the bulk imports
    among the last N runs - otherwise a burst of webhook imports hides them."""
    history.add_run(RUN_TYPE_BULK, "nightly.txt", _iso(5), _iso(5), TRIGGER_SCHEDULED, OUTCOME_SUCCESS)
    for n in range(10):
        history.add_run(RUN_TYPE_WEBHOOK, f"Import {n}", _iso(1), _iso(1), TRIGGER_RADARR, OUTCOME_SUCCESS)

    runs = history.get_runs(limit=3, run_type=RUN_TYPE_BULK)

    assert [run["label"] for run in runs] == ["nightly.txt"]


@pytest.mark.unit
def test_records_every_outcome(history):
    for outcome in (OUTCOME_SUCCESS, OUTCOME_PARTIAL, OUTCOME_STOPPED, OUTCOME_FAILED, OUTCOME_SKIPPED):
        history.add_run(RUN_TYPE_BULK, "bulk_import.txt", _iso(), _iso(), TRIGGER_MANUAL, outcome)

    outcomes = {run["outcome"] for run in history.get_runs()}

    assert outcomes == {OUTCOME_SUCCESS, OUTCOME_PARTIAL, OUTCOME_STOPPED, OUTCOME_FAILED, OUTCOME_SKIPPED}


@pytest.mark.unit
def test_prunes_by_entry_count(tmp_path):
    history = RunHistory(str(tmp_path / "run_history.json"), max_entries=3, max_age_days=0)

    for n in range(5):
        history.add_run(RUN_TYPE_BULK, f"file{n}.txt", _iso(), _iso(), TRIGGER_MANUAL, OUTCOME_SUCCESS)

    runs = history.get_runs()

    assert len(runs) == 3
    assert [run["label"] for run in runs] == ["file4.txt", "file3.txt", "file2.txt"]


@pytest.mark.unit
def test_the_entry_cap_is_counted_per_run_type(tmp_path):
    """A busy library takes dozens of webhook imports a day. They must not push the
    nightly bulk import out of the history."""
    history = RunHistory(str(tmp_path / "run_history.json"), max_entries=3, max_age_days=0)

    history.add_run(RUN_TYPE_BULK, "nightly.txt", _iso(), _iso(), TRIGGER_SCHEDULED, OUTCOME_SUCCESS)
    for n in range(10):
        history.add_run(RUN_TYPE_WEBHOOK, f"Import {n}", _iso(), _iso(), TRIGGER_RADARR, OUTCOME_SUCCESS)

    assert [run["label"] for run in history.get_runs(run_type=RUN_TYPE_BULK)] == ["nightly.txt"]
    assert len(history.get_runs(run_type=RUN_TYPE_WEBHOOK)) == 3


@pytest.mark.unit
def test_prunes_by_age(tmp_path):
    history = RunHistory(str(tmp_path / "run_history.json"), max_entries=0, max_age_days=30)

    history.add_run(RUN_TYPE_BULK, "old.txt", _iso(60), _iso(60), TRIGGER_MANUAL, OUTCOME_SUCCESS)
    history.add_run(RUN_TYPE_BULK, "recent.txt", _iso(1), _iso(1), TRIGGER_MANUAL, OUTCOME_SUCCESS)

    labels = [run["label"] for run in history.get_runs()]

    assert labels == ["recent.txt"]


@pytest.mark.unit
def test_records_written_before_run_types_still_render(tmp_path):
    """An existing history file holds bulk imports keyed by filename and a scheduled
    boolean. Reading one must fill in the fields the table now expects."""
    path = tmp_path / "run_history.json"
    path.write_text(json.dumps([{
        "filename": "bulk_import.txt",
        "started_at": _iso(1),
        "ended_at": _iso(1),
        "scheduled": True,
        "outcome": OUTCOME_SUCCESS,
        "assets_processed": 3,
        "success_count": 3,
        "cached_count": 0,
        "locked_count": 0,
        "error_count": 0,
    }]), encoding="utf-8")

    run = RunHistory(str(path)).get_runs()[0]

    assert run["run_type"] == RUN_TYPE_BULK
    assert run["label"] == "bulk_import.txt"
    assert run["trigger"] == TRIGGER_SCHEDULED
    assert run["assets_processed"] == 3


@pytest.mark.unit
def test_an_old_manual_record_reads_as_manually_triggered(tmp_path):
    path = tmp_path / "run_history.json"
    path.write_text(json.dumps([{
        "filename": "bulk_import.txt", "started_at": _iso(1), "ended_at": _iso(1),
        "scheduled": False, "outcome": OUTCOME_SUCCESS,
    }]), encoding="utf-8")

    assert RunHistory(str(path)).get_runs()[0]["trigger"] == TRIGGER_MANUAL


@pytest.mark.unit
def test_survives_across_instances(tmp_path):
    path = str(tmp_path / "run_history.json")
    RunHistory(path).add_run(RUN_TYPE_BULK, "bulk_import.txt", _iso(), _iso(), TRIGGER_MANUAL, OUTCOME_SUCCESS)

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
    history.add_run(RUN_TYPE_BULK, "bulk_import.txt", _iso(), _iso(), TRIGGER_MANUAL, OUTCOME_SUCCESS)

    assert len(history.get_runs()) == 1
    assert json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.unit
def test_concurrent_runs_finishing_together_do_not_lose_a_record(tmp_path):
    """A scheduled run landing at the same moment as a webhook import must not have one
    read-modify-write clobber the other's record."""
    path = str(tmp_path / "run_history.json")

    def add(n):
        RunHistory(path).add_run(RUN_TYPE_BULK, f"file{n}.txt", _iso(), _iso(), TRIGGER_MANUAL, OUTCOME_SUCCESS)

    threads = [threading.Thread(target=add, args=(n,)) for n in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(RunHistory(path).get_runs()) == 20
