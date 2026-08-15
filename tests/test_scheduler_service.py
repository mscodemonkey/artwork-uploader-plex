"""Unit tests for services/scheduler_service.py: multi-schedule handling, the
config.json schedule migration, missed-run catch-up logic and the overlap guard."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest
import schedule

from core.config import Config
from models.bulk_schedule import BulkSchedule
from services.scheduler_service import SchedulerService


@pytest.fixture(autouse=True)
def clean_schedule_registry():
    """The `schedule` library keeps a module-level job registry, so clear it around every test."""
    schedule.clear()
    yield
    schedule.clear()


@pytest.fixture
def service():
    return SchedulerService()


def run_job(service, job_id):
    """Directly invoke a scheduled job's function, without waiting for the schedule library's clock."""
    service.scheduled_jobs[job_id].job_func()


# ------------------------------- add_schedule -------------------------------

@pytest.mark.unit
def test_daily_schedule_runs_with_its_filename(service):
    calls = []
    sched = BulkSchedule(file="bulk_a.txt", time="02:00")
    job_id = service.add_schedule(sched, calls.append)

    run_job(service, job_id)

    assert calls == ["bulk_a.txt"]


@pytest.mark.unit
def test_interval_schedule_in_hours(service):
    calls = []
    sched = BulkSchedule(file="bulk_a.txt", interval_value=6, interval_unit="hours")
    job_id = service.add_schedule(sched, calls.append)

    run_job(service, job_id)

    assert calls == ["bulk_a.txt"]
    assert service.schedule_meta[job_id]["file"] == "bulk_a.txt"
    assert service.schedule_meta[job_id]["interval_value"] == 6
    assert service.schedule_meta[job_id]["interval_unit"] == "hours"


@pytest.mark.unit
def test_interval_schedule_in_days(service):
    sched = BulkSchedule(file="bulk_a.txt", interval_value=2, interval_unit="days")
    job_id = service.add_schedule(sched, lambda f: None)
    assert service.schedule_meta[job_id]["interval_unit"] == "days"


@pytest.mark.unit
def test_add_schedule_requires_a_time_or_a_valid_interval(service):
    with pytest.raises(ValueError):
        invalid_sched1 = BulkSchedule(file="bulk_a.txt")
        service.add_schedule(invalid_sched1, lambda f: None)

    with pytest.raises(ValueError):
        invalid_sched2 = BulkSchedule(file="bulk_a.txt", interval_value=3, interval_unit="fortnights")
        service.add_schedule(invalid_sched2, lambda f: None)


@pytest.mark.unit
def test_a_file_can_carry_more_than_one_schedule(service):
    """A bulk file can carry multiple distinct schedules."""
    sched1 = BulkSchedule(file="bulk_a.txt", time="02:00")
    sched2 = BulkSchedule(file="bulk_a.txt", interval_value=6, interval_unit="hours")

    first = service.add_schedule(sched1, lambda f: None)
    second = service.add_schedule(sched2, lambda f: None)

    assert first != second
    assert set(service.get_all_job_ids()) == {first, second}
    assert set(service.get_jobs_for_file("bulk_a.txt")) == {first, second}


@pytest.mark.unit
def test_add_schedule_reuses_a_given_id(service):
    sched = BulkSchedule(id="my-id", file="bulk_a.txt", time="02:00")
    job_id = service.add_schedule(sched, lambda f: None)
    assert job_id == "my-id"
    assert "my-id" in service.scheduled_jobs


# ------------------------------- remove_schedule -------------------------------

@pytest.mark.unit
def test_remove_schedule_only_removes_the_one_job(service):
    sched_keep = BulkSchedule(file="bulk_a.txt", time="02:00")
    sched_remove = BulkSchedule(file="bulk_a.txt", time="12:30")

    keep = service.add_schedule(sched_keep, lambda f: None)
    remove = service.add_schedule(sched_remove, lambda f: None)

    assert service.remove_schedule(remove) is True

    assert keep in service.scheduled_jobs
    assert remove not in service.scheduled_jobs
    assert service.get_jobs_for_file("bulk_a.txt") == [keep]


@pytest.mark.unit
def test_remove_schedule_returns_false_when_not_found(service):
    assert service.remove_schedule("does-not-exist") is False


# ------------------------------- rename_file -------------------------------

@pytest.mark.unit
def test_rename_file_moves_every_schedule_for_that_file(service):
    calls = []
    a = service.add_schedule(BulkSchedule(file="old.txt", time="02:00"), calls.append)
    b = service.add_schedule(BulkSchedule(file="old.txt", interval_value=6, interval_unit="hours"), calls.append)
    other = service.add_schedule(BulkSchedule(file="unrelated.txt", time="09:00"), calls.append)

    renamed_ids = service.rename_file("old.txt", "new.txt")

    assert set(renamed_ids) == {a, b}
    assert service.schedule_meta[a]["file"] == "new.txt"
    assert service.schedule_meta[b]["file"] == "new.txt"
    assert service.schedule_meta[other]["file"] == "unrelated.txt"


@pytest.mark.unit
def test_rename_file_does_not_recreate_the_underlying_job(service):
    """Renaming should only touch metadata - the schedule library job stays the same object."""
    job_id = service.add_schedule(BulkSchedule(file="old.txt", time="02:00"), lambda f: None)
    job_before = service.scheduled_jobs[job_id]

    service.rename_file("old.txt", "new.txt")

    assert service.scheduled_jobs[job_id] is job_before


@pytest.mark.unit
def test_renamed_schedule_calls_back_with_the_new_filename(service):
    calls = []
    job_id = service.add_schedule(BulkSchedule(file="old.txt", time="02:00"), calls.append)

    service.rename_file("old.txt", "new.txt")
    run_job(service, job_id)

    assert calls == ["new.txt"]


# ------------------------------- housekeeping -------------------------------

@pytest.mark.unit
def test_has_schedules(service):
    assert service.has_schedules() is False
    service.add_schedule(BulkSchedule(file="bulk_a.txt", time="02:00"), lambda f: None)
    assert service.has_schedules() is True


@pytest.mark.unit
def test_clear_all_schedules(service):
    service.add_schedule(BulkSchedule(file="bulk_a.txt", time="02:00"), lambda f: None)
    service.add_schedule(BulkSchedule(file="bulk_b.txt", interval_value=1, interval_unit="days"), lambda f: None)

    service.clear_all_schedules()

    assert service.get_all_job_ids() == []
    assert service.schedule_meta == {}
    assert len(schedule.jobs) == 0


# ------------------------------- config.json migration -------------------------------

@pytest.mark.unit
def test_legacy_schedule_entries_are_migrated_with_an_id(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "schedules": [
            {"file": "bulk_a.txt", "time": "02:00"},
            {"file": "bulk_b.txt", "time": "12:30"},
        ]
    }))

    config = Config(str(config_path))
    config.load()

    assert len(config.schedules) == 2
    ids = [s["id"] for s in config.schedules]
    assert all(ids)
    assert len(set(ids)) == 2
    assert config.schedules[0]["file"] == "bulk_a.txt"
    assert config.schedules[0]["time"] == "02:00"


@pytest.mark.unit
def test_migration_keeps_an_existing_id_stable(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "schedules": [{"id": "already-has-one", "file": "bulk_a.txt", "time": "02:00"}],
    }))

    config = Config(str(config_path))
    config.load()

    assert config.schedules[0]["id"] == "already-has-one"


@pytest.mark.unit
def test_migrated_ids_are_written_back_to_disk_and_stay_stable(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "schedules": [{"file": "bulk_a.txt", "time": "02:00"}],
    }))

    first = Config(str(config_path))
    first.load()
    first_id = first.schedules[0]["id"]

    on_disk = json.loads(config_path.read_text())
    assert on_disk["schedules"][0]["id"] == first_id

    second = Config(str(config_path))
    second.load()
    assert second.schedules[0]["id"] == first_id


@pytest.mark.unit
def test_deleting_a_migrated_schedule_stays_deleted_after_reload(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "schedules": [{"file": "bulk_a.txt", "time": "02:00"}],
    }))

    config = Config(str(config_path))
    config.load()
    schedule_id = config.schedules[0]["id"]

    config.load()
    config.schedules = [s for s in config.schedules if s.get("id") != schedule_id]
    config.save()

    reloaded = Config(str(config_path))
    reloaded.load()
    assert reloaded.schedules == []


@pytest.mark.unit
def test_editing_a_migrated_schedule_updates_in_place_after_reload(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "schedules": [{"file": "bulk_a.txt", "time": "02:00"}],
    }))

    config = Config(str(config_path))
    config.load()
    schedule_id = config.schedules[0]["id"]

    config.load()
    matched = False
    for each_schedule in config.schedules:
        if each_schedule.get("id") == schedule_id:
            each_schedule["time"] = "12:30"
            matched = True
    if not matched:
        config.schedules.append({"id": schedule_id, "file": "bulk_a.txt", "time": "12:30"})
    config.save()

    reloaded = Config(str(config_path))
    reloaded.load()
    assert len(reloaded.schedules) == 1
    assert reloaded.schedules[0]["time"] == "12:30"


@pytest.mark.unit
def test_renaming_a_migrated_schedules_file_survives_reload(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "schedules": [{"file": "old.txt", "time": "02:00"}],
    }))

    config = Config(str(config_path))
    config.load()
    schedule_id = config.schedules[0]["id"]

    config.load()
    for each_schedule in config.schedules:
        if each_schedule.get("id") == schedule_id:
            each_schedule["file"] = "new.txt"
    config.save()

    reloaded = Config(str(config_path))
    reloaded.load()
    assert reloaded.schedules[0]["file"] == "new.txt"


@pytest.mark.unit
def test_multiple_schedules_for_one_file_survive_a_save_and_reload(tmp_path):
    config_path = tmp_path / "config.json"
    config = Config(str(config_path))
    config.create()
    config.load()

    config.schedules = [
        {"id": "a", "file": "bulk_a.txt", "time": "02:00"},
        {"id": "b", "file": "bulk_a.txt", "interval_value": 6, "interval_unit": "hours"},
    ]
    config.save()

    reloaded = Config(str(config_path))
    reloaded.load()

    assert len(reloaded.schedules) == 2
    assert {s["id"] for s in reloaded.schedules} == {"a", "b"}
    by_id = {s["id"]: s for s in reloaded.schedules}
    assert by_id["a"]["file"] == "bulk_a.txt"
    assert by_id["a"]["time"] == "02:00"
    assert by_id["b"]["interval_value"] == 6
    assert by_id["b"]["interval_unit"] == "hours"


# ------------------------------- get_missed_run -------------------------------

@pytest.mark.unit
def test_no_catch_up_when_never_run_before():
    """A schedule with no recorded last run is never treated as having missed one."""
    mock_now = datetime(2026, 8, 9, 7, 30)
    sched = BulkSchedule(time="02:00", last_run=None)

    with patch("services.scheduler_service.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat

        due, within_window = SchedulerService.get_missed_run(sched, window=60)

    assert due is None
    assert within_window is False


@pytest.mark.unit
def test_missed_run_within_the_catch_up_window():
    mock_now = datetime(2026, 8, 9, 2, 15)
    last_run = datetime(2026, 8, 8, 2, 0).isoformat()
    sched = BulkSchedule(time="02:00", last_run=last_run)

    with patch("services.scheduler_service.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat

        due, within_window = SchedulerService.get_missed_run(sched, window=30)

    assert due == datetime(2026, 8, 9, 2, 0)
    assert within_window is True


@pytest.mark.unit
def test_missed_run_outside_the_catch_up_window():
    mock_now = datetime(2026, 8, 9, 7, 30)
    last_run = datetime(2026, 8, 8, 2, 0).isoformat()
    sched = BulkSchedule(time="02:00", last_run=last_run)

    with patch("services.scheduler_service.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat

        due, within_window = SchedulerService.get_missed_run(sched, window=60)

    assert due == datetime(2026, 8, 9, 2, 0)
    assert within_window is False


@pytest.mark.unit
def test_zero_window_never_catches_up():
    mock_now = datetime(2026, 8, 9, 2, 5)
    last_run = datetime(2026, 8, 8, 2, 0).isoformat()
    sched = BulkSchedule(time="02:00", last_run=last_run)

    with patch("services.scheduler_service.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat

        due, within_window = SchedulerService.get_missed_run(sched, window=0)

    assert due == datetime(2026, 8, 9, 2, 0)
    assert within_window is False


@pytest.mark.unit
def test_already_ran_today_is_not_a_miss():
    mock_now = datetime(2026, 8, 9, 7, 30)
    last_run = datetime(2026, 8, 9, 2, 0).isoformat()
    sched = BulkSchedule(time="02:00", last_run=last_run)

    with patch("services.scheduler_service.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat

        due, within_window = SchedulerService.get_missed_run(sched, window=60)

    assert due is None
    assert within_window is False


@pytest.mark.unit
def test_due_time_is_still_ahead_today_uses_yesterdays_occurrence():
    """If it's not yet 02:00 today, the most recent due time was yesterday's run."""
    mock_now = datetime(2026, 8, 9, 1, 0)
    last_run = datetime(2026, 8, 7, 2, 0).isoformat()
    sched = BulkSchedule(time="02:00", last_run=last_run)

    with patch("services.scheduler_service.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat

        due, within_window = SchedulerService.get_missed_run(sched, window=1440)

    assert due == datetime(2026, 8, 8, 2, 0)
    assert within_window is True


@pytest.mark.unit
def test_malformed_schedule_time_is_not_a_miss():
    mock_now = datetime(2026, 8, 9, 7, 30)
    last_run = datetime(2026, 8, 8, 2, 0).isoformat()
    sched = BulkSchedule(time="not-a-time", last_run=last_run)

    with patch("services.scheduler_service.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat

        due, within_window = SchedulerService.get_missed_run(sched, window=60)

    assert due is None
    assert within_window is False


@pytest.mark.unit
def test_malformed_last_run_is_not_a_miss():
    mock_now = datetime(2026, 8, 9, 2, 5)
    sched = BulkSchedule(time="02:00", last_run="not-a-timestamp")

    with patch("services.scheduler_service.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat

        due, within_window = SchedulerService.get_missed_run(sched, window=60)

    assert due is None
    assert within_window is False


# ------------------------------- overlap guard -------------------------------

@pytest.mark.unit
def test_overlap_guard_blocks_a_second_start_for_the_same_file():
    service = SchedulerService()
    assert service.try_start("bulk_import.txt") is True
    assert service.try_start("bulk_import.txt") is False

    service.finish("bulk_import.txt")
    assert service.try_start("bulk_import.txt") is True


@pytest.mark.unit
def test_overlap_guard_is_independent_per_file():
    service = SchedulerService()
    assert service.try_start("a.txt") is True
    assert service.try_start("b.txt") is True