"""
Tests for the scheduled-run catch-up wiring in artwork_uploader.py.

services/test_scheduler_service.py covers the pure missed-run calculation and the
overlap-guard primitives in isolation. This file covers how artwork_uploader.py wires
those primitives together: recording a run, skipping a run that would collide with one
already in flight, and choosing whether a missed run is caught up or just logged.
"""

from datetime import datetime as real_datetime
from unittest.mock import MagicMock, patch
import uuid
import schedule

import pytest

import core.globals as globals
from artwork_uploader import (
    add_file_to_schedule_thread,
    catch_up_missed_schedule,
    record_schedule_run,
    setup_scheduler_on_first_load,
)
from models.bulk_schedule import BulkSchedule
from models.instance import Instance
from services.scheduler_service import SchedulerService

pytestmark = pytest.mark.unit


class FakeConfig:
    """Stands in for core.config.Config: only the attributes this wiring touches."""

    def __init__(self, schedules=None, catch_up_window_minutes=0):
        self.schedules = schedules if schedules is not None else []
        self.catch_up_window_minutes = catch_up_window_minutes
        self.save = MagicMock()


@pytest.fixture
def scheduler():
    previous_config = globals.config
    previous_scheduler = globals.scheduler_service
    globals.scheduler_service = SchedulerService()
    yield globals.scheduler_service
    globals.config = previous_config
    globals.scheduler_service = previous_scheduler


def test_record_schedule_run_stamps_last_run_and_saves(scheduler):
    schedule_id = str(uuid.uuid4())
    config = FakeConfig(schedules=[{"id": schedule_id, "file": "bulk_import.txt", "time": "02:00"}])
    globals.config = config

    record_schedule_run(schedule_id=schedule_id)

    assert "last_run" in config.schedules[0]
    assert config.schedules[0]["last_run"]  # non-empty ISO timestamp
    config.save.assert_called_once()


def test_record_schedule_run_is_a_no_op_for_an_unknown_id(scheduler):
    schedule_id = str(uuid.uuid4())
    config = FakeConfig(schedules=[{"id": schedule_id, "file": "bulk_import.txt", "time": "02:00"}])
    globals.config = config

    some_other_id = str(uuid.uuid4())
    record_schedule_run(schedule_id=some_other_id)

    assert "last_run" not in config.schedules[0]
    config.save.assert_called_once()


def test_add_file_to_schedule_thread_starts_the_run_and_marks_it_running(scheduler):
    schedule_id = str(uuid.uuid4())
    globals.config = FakeConfig(schedules=[{"id": schedule_id, "file": "bulk_import.txt", "time": "02:00"}])
    instance = Instance(mode="cli")

    with patch("artwork_uploader.threading.Thread") as mock_thread:
        add_file_to_schedule_thread(instance, "bulk_import.txt", schedule_id)

    mock_thread.assert_called_once()
    assert scheduler.try_start("bulk_import.txt") is False  # still marked running
    scheduler.finish("bulk_import.txt")


def test_add_file_to_schedule_thread_skips_when_a_run_is_already_in_progress(scheduler):
    schedule_id = str(uuid.uuid4())
    globals.config = FakeConfig(schedules=[{"id": schedule_id, "file": "bulk_import.txt", "time": "02:00"}])
    instance = Instance(mode="cli")
    scheduler.try_start("bulk_import.txt")  # simulate a run already in flight

    with patch("artwork_uploader.threading.Thread") as mock_thread:
        add_file_to_schedule_thread(instance, "bulk_import.txt", schedule_id)

    mock_thread.assert_not_called()
    assert globals.config.schedules[0].get("last_run") is None  # no run was recorded


def test_add_file_to_schedule_thread_is_a_no_op_without_an_instance(scheduler):
    schedule_id = str(uuid.uuid4())
    globals.config = FakeConfig(schedules=[{"id": schedule_id, "file": "bulk_import.txt", "time": "02:00"}])

    with patch("artwork_uploader.threading.Thread") as mock_thread:
        add_file_to_schedule_thread(None, "bulk_import.txt", schedule_id)

    mock_thread.assert_not_called()


def test_catch_up_missed_schedule_triggers_a_run_inside_the_window(scheduler):
    schedule_id = str(uuid.uuid4())
    globals.config = FakeConfig(catch_up_window_minutes=1440)
    instance = Instance(mode="cli")
    last_run_yesterday = "2026-08-08T02:00:00"

    sched = BulkSchedule(
        id=schedule_id,
        file="bulk_import.txt",
        time="02:00",
        last_run=last_run_yesterday
    )

    with patch("services.scheduler_service.datetime") as mock_datetime, \
         patch("artwork_uploader.add_file_to_schedule_thread") as mock_add:
        mock_datetime.now.return_value = real_datetime(2026, 8, 9, 3, 0)
        mock_datetime.fromisoformat = real_datetime.fromisoformat
        catch_up_missed_schedule(instance, sched)

    mock_add.assert_called_once_with(instance, "bulk_import.txt", schedule_id)


def test_catch_up_missed_schedule_only_logs_when_outside_the_window(scheduler):
    schedule_id = str(uuid.uuid4())
    globals.config = FakeConfig(catch_up_window_minutes=30)
    instance = Instance(mode="cli")
    last_run_yesterday = "2026-08-08T02:00:00"

    sched = BulkSchedule(
        id=schedule_id,
        file="bulk_import.txt",
        time="02:00",
        last_run=last_run_yesterday
    )

    with patch("services.scheduler_service.datetime") as mock_datetime, \
         patch("artwork_uploader.add_file_to_schedule_thread") as mock_add, \
         patch("artwork_uploader.update_log") as mock_log:
        mock_datetime.now.return_value = real_datetime(2026, 8, 9, 7, 30)
        mock_datetime.fromisoformat = real_datetime.fromisoformat
        catch_up_missed_schedule(instance, sched)

    mock_add.assert_not_called()
    assert mock_log.call_count == 1
    logged_message = mock_log.call_args[0][1]
    assert "missed" in logged_message.lower()
    assert "02:00" in logged_message


def test_catch_up_missed_schedule_does_nothing_for_a_never_run_schedule(scheduler):
    schedule_id = str(uuid.uuid4())
    globals.config = FakeConfig(catch_up_window_minutes=1440)
    instance = Instance(mode="cli")

    sched = BulkSchedule(
        id=schedule_id,
        file="bulk_import.txt",
        time="02:00",
        last_run=None
    )

    with patch("artwork_uploader.add_file_to_schedule_thread") as mock_add, \
         patch("artwork_uploader.update_log") as mock_log:
        catch_up_missed_schedule(instance, sched)

    mock_add.assert_not_called()
    mock_log.assert_not_called()


def test_catch_up_missed_interval_schedule_triggers_a_run_inside_the_window(scheduler):
    schedule_id = str(uuid.uuid4())
    globals.config = FakeConfig(catch_up_window_minutes=120)  # 2-hour window
    instance = Instance(mode="cli")
    last_run_6h_ago = "2026-08-09T02:00:00"

    sched = BulkSchedule(
        id=schedule_id,
        file="bulk_import.txt",
        interval_value=6,
        interval_unit="hours",
        last_run=last_run_6h_ago
    )

    with patch("services.scheduler_service.datetime") as mock_datetime, \
         patch("artwork_uploader.add_file_to_schedule_thread") as mock_add:
        # Current time is 08:30 (missed by 30 mins, well within 120-min window)
        mock_datetime.now.return_value = real_datetime(2026, 8, 9, 8, 30)
        mock_datetime.fromisoformat = real_datetime.fromisoformat
        catch_up_missed_schedule(instance, sched)

    mock_add.assert_called_once_with(instance, "bulk_import.txt", schedule_id)


def test_catch_up_missed_interval_schedule_only_logs_when_outside_the_window(scheduler):
    schedule_id = str(uuid.uuid4())
    globals.config = FakeConfig(catch_up_window_minutes=30)  # 30-min window
    instance = Instance(mode="cli")
    last_run = "2026-08-09T02:00:00"

    sched = BulkSchedule(
        id=schedule_id,
        file="bulk_import.txt",
        interval_value=6,
        interval_unit="hours",
        last_run=last_run
    )

    with patch("services.scheduler_service.datetime") as mock_datetime, \
         patch("artwork_uploader.add_file_to_schedule_thread") as mock_add, \
         patch("artwork_uploader.update_log") as mock_log:
        # Current time is 09:30 (missed by 1.5 hours, outside 30-min window)
        mock_datetime.now.return_value = real_datetime(2026, 8, 9, 9, 30)
        mock_datetime.fromisoformat = real_datetime.fromisoformat
        catch_up_missed_schedule(instance, sched)

    mock_add.assert_not_called()
    assert mock_log.call_count == 1
    logged_message = mock_log.call_args[0][1]
    assert "missed" in logged_message.lower()


def test_catch_up_missed_interval_schedule_does_nothing_for_never_run_schedule(scheduler):
    schedule_id = str(uuid.uuid4())
    globals.config = FakeConfig(catch_up_window_minutes=120)
    instance = Instance(mode="cli")

    sched = BulkSchedule(
        id=schedule_id,
        file="bulk_import.txt",
        interval_value=6,
        interval_unit="hours",
        last_run=None
    )

    with patch("artwork_uploader.add_file_to_schedule_thread") as mock_add, \
         patch("artwork_uploader.update_log") as mock_log:
        catch_up_missed_schedule(instance, sched)

    mock_add.assert_not_called()
    mock_log.assert_not_called()


def test_setup_scheduler_aligns_next_run_on_startup(scheduler):
    """Verifies that starting up aligns job.next_run to the computed next run target 
    for never run before tasks instead of naively resetting to now + interval.
    Tasks that were previously run should have a computed next_run attribute and it should
    be respected.
    """
    schedule_interval_id = str(uuid.uuid4())
    schedule_daily_id = str(uuid.uuid4())
    schedule_never_run_interval_id = str(uuid.uuid4())
    schedule_never_run_daily_id = str(uuid.uuid4())

    globals.config = FakeConfig(schedules=[
        {
            "id": schedule_interval_id,
            "file": "interval_task.txt",
            "interval_value": 6,
            "interval_unit": "hours",
            "last_run": "2026-08-09T02:00:00",
            "next_run": "2026-08-09T08:00:00",
            "last_run_status": "success"
        },
        {
            "id": schedule_daily_id,
            "file": "daily_task.txt",
            "time": "02:00",
            "last_run": "2026-08-09T02:00:00",
            "next_run": "2026-08-10T02:00:00",
            "last_run_status": "stopped"
        },
        {
            "id": schedule_never_run_interval_id,
            "file": "never_run_interval_task.txt",
            "interval_value": 2,
            "interval_unit": "hours",
            "last_run_status": "never_run"
        },
        {
            "id": schedule_never_run_daily_id,
            "file": "never_run_daily_task.txt",
            "time": "05:30",
            "last_run_status": "never_run"
        }
    ])
    instance = Instance(mode="cli")

    fake_now = real_datetime(2026, 8, 9, 5, 0)

    class MockDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    with patch.object(schedule.datetime, "datetime", MockDateTime), \
         patch("artwork_uploader.datetime", MockDateTime), \
         patch("services.scheduler_service.datetime", MockDateTime), \
         patch("models.bulk_schedule.datetime", MockDateTime), \
         patch("artwork_uploader.update_log"), \
         patch("artwork_uploader.debug_me"):

        try:
            setup_scheduler_on_first_load(instance)

            # 1. Interval task: last_run 02:00 + 6h -> expected 08:00 on 2026-08-09
            interval_job = scheduler.scheduled_jobs[schedule_interval_id]
            assert interval_job.next_run == real_datetime(2026, 8, 9, 8, 0, 0)

            # 2. Daily task: time 02:00 (already passed at 05:00) -> expected 02:00 on 2026-08-10
            daily_job = scheduler.scheduled_jobs[schedule_daily_id]
            assert daily_job.next_run == real_datetime(2026, 8, 10, 2, 0, 0)

            # 3. Never run before interval task: time should be now (05:00) plus interval (2h) -> expected 07:00 on 2026-08-09
            never_run_interval_job = scheduler.scheduled_jobs[schedule_never_run_interval_id]
            assert never_run_interval_job.next_run == real_datetime(2026, 8, 9, 7, 0, 0)

            # 4. Never run before daily task: expected 05:30 on 2026-08-09
            never_run_daily_job = scheduler.scheduled_jobs[schedule_never_run_daily_id]
            assert never_run_daily_job.next_run == real_datetime(2026, 8, 9, 5, 30, 0)

        finally:
            scheduler.stop()
            scheduler.clear_all_schedules()

def test_setup_scheduler_skips_an_invalid_persisted_schedule(scheduler):
    """One malformed entry in config.json must not stop the app starting or
    block the valid schedules from registering."""
    globals.config = FakeConfig(schedules=[
        {"id": "bad", "file": "a.txt"},
        {"id": "good", "file": "b.txt", "time": "02:00"},
    ])
    instance = Instance(mode="cli")

    try:
        with patch("artwork_uploader.update_log"), patch("artwork_uploader.debug_me"):
            setup_scheduler_on_first_load(instance)

        assert scheduler.get_jobs_for_file("b.txt") == ["good"]
        assert scheduler.get_jobs_for_file("a.txt") == []
    finally:
        scheduler.stop()
        scheduler.clear_all_schedules()