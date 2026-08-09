"""
Tests for the scheduled-run catch-up wiring in artwork_uploader.py.

services/test_scheduler_service.py covers the pure missed-run calculation and the
overlap-guard primitives in isolation. This file covers how artwork_uploader.py wires
those primitives together: recording a run, skipping a run that would collide with one
already in flight, and choosing whether a missed run is caught up or just logged.
"""

from unittest.mock import MagicMock, patch

import pytest

import core.globals as globals
from artwork_uploader import add_file_to_schedule_thread, catch_up_missed_schedule, record_schedule_run
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
    config = FakeConfig(schedules=[{"file": "bulk_import.txt", "time": "02:00"}])
    globals.config = config

    record_schedule_run("bulk_import.txt")

    assert "last_run" in config.schedules[0]
    assert config.schedules[0]["last_run"]  # non-empty ISO timestamp
    config.save.assert_called_once()


def test_record_schedule_run_is_a_no_op_for_an_unknown_file(scheduler):
    config = FakeConfig(schedules=[{"file": "bulk_import.txt", "time": "02:00"}])
    globals.config = config

    record_schedule_run("some_other_file.txt")

    assert "last_run" not in config.schedules[0]
    config.save.assert_called_once()


def test_add_file_to_schedule_thread_starts_the_run_and_marks_it_running(scheduler):
    globals.config = FakeConfig(schedules=[{"file": "bulk_import.txt", "time": "02:00"}])
    instance = Instance(mode="cli")

    with patch("artwork_uploader.threading.Thread") as mock_thread:
        add_file_to_schedule_thread(instance, "bulk_import.txt")

    mock_thread.assert_called_once()
    assert scheduler.try_start("bulk_import.txt") is False  # still marked running
    scheduler.finish("bulk_import.txt")


def test_add_file_to_schedule_thread_skips_when_a_run_is_already_in_progress(scheduler):
    globals.config = FakeConfig(schedules=[{"file": "bulk_import.txt", "time": "02:00"}])
    instance = Instance(mode="cli")
    scheduler.try_start("bulk_import.txt")  # simulate a run already in flight

    with patch("artwork_uploader.threading.Thread") as mock_thread:
        add_file_to_schedule_thread(instance, "bulk_import.txt")

    mock_thread.assert_not_called()
    assert globals.config.schedules[0].get("last_run") is None  # no run was recorded


def test_add_file_to_schedule_thread_is_a_no_op_without_an_instance(scheduler):
    globals.config = FakeConfig(schedules=[{"file": "bulk_import.txt", "time": "02:00"}])

    with patch("artwork_uploader.threading.Thread") as mock_thread:
        add_file_to_schedule_thread(None, "bulk_import.txt")

    mock_thread.assert_not_called()


def test_catch_up_missed_schedule_triggers_a_run_inside_the_window(scheduler):
    globals.config = FakeConfig(catch_up_window_minutes=1440)
    instance = Instance(mode="cli")
    last_run_yesterday = "2026-08-08T02:00:00"

    with patch("artwork_uploader.datetime") as mock_datetime, \
         patch("artwork_uploader.add_file_to_schedule_thread") as mock_add:
        from datetime import datetime as real_datetime
        mock_datetime.now.return_value = real_datetime(2026, 8, 9, 3, 0)
        catch_up_missed_schedule(instance, "bulk_import.txt", "02:00", last_run_yesterday)

    mock_add.assert_called_once_with(instance, "bulk_import.txt")


def test_catch_up_missed_schedule_only_logs_when_outside_the_window(scheduler):
    globals.config = FakeConfig(catch_up_window_minutes=30)
    instance = Instance(mode="cli")
    last_run_yesterday = "2026-08-08T02:00:00"

    with patch("artwork_uploader.datetime") as mock_datetime, \
         patch("artwork_uploader.add_file_to_schedule_thread") as mock_add, \
         patch("artwork_uploader.update_log") as mock_log:
        from datetime import datetime as real_datetime
        mock_datetime.now.return_value = real_datetime(2026, 8, 9, 7, 30)
        catch_up_missed_schedule(instance, "bulk_import.txt", "02:00", last_run_yesterday)

    mock_add.assert_not_called()
    assert mock_log.call_count == 1
    logged_message = mock_log.call_args[0][1]
    assert "missed" in logged_message.lower()
    assert "02:00" in logged_message


def test_catch_up_missed_schedule_does_nothing_for_a_never_run_schedule(scheduler):
    globals.config = FakeConfig(catch_up_window_minutes=1440)
    instance = Instance(mode="cli")

    with patch("artwork_uploader.add_file_to_schedule_thread") as mock_add, \
         patch("artwork_uploader.update_log") as mock_log:
        catch_up_missed_schedule(instance, "bulk_import.txt", "02:00", None)

    mock_add.assert_not_called()
    mock_log.assert_not_called()
