"""Unit tests for the scheduler service's missed-run catch-up logic and overlap guard."""

import pytest
from datetime import datetime

from services.scheduler_service import SchedulerService


pytestmark = pytest.mark.unit


def test_no_catch_up_when_never_run_before():
    """A schedule with no recorded last run is never treated as having missed one."""
    now = datetime(2026, 8, 9, 7, 30)
    due, within_window = SchedulerService.get_missed_run("02:00", None, now, window_minutes=60)
    assert due is None
    assert within_window is False


def test_missed_run_within_the_catch_up_window():
    now = datetime(2026, 8, 9, 2, 15)
    last_run = datetime(2026, 8, 8, 2, 0).isoformat()
    due, within_window = SchedulerService.get_missed_run("02:00", last_run, now, window_minutes=30)
    assert due == datetime(2026, 8, 9, 2, 0)
    assert within_window is True


def test_missed_run_outside_the_catch_up_window():
    now = datetime(2026, 8, 9, 7, 30)
    last_run = datetime(2026, 8, 8, 2, 0).isoformat()
    due, within_window = SchedulerService.get_missed_run("02:00", last_run, now, window_minutes=60)
    assert due == datetime(2026, 8, 9, 2, 0)
    assert within_window is False


def test_zero_window_never_catches_up():
    now = datetime(2026, 8, 9, 2, 5)
    last_run = datetime(2026, 8, 8, 2, 0).isoformat()
    due, within_window = SchedulerService.get_missed_run("02:00", last_run, now, window_minutes=0)
    assert due == datetime(2026, 8, 9, 2, 0)
    assert within_window is False


def test_already_ran_today_is_not_a_miss():
    now = datetime(2026, 8, 9, 7, 30)
    last_run = datetime(2026, 8, 9, 2, 0).isoformat()
    due, within_window = SchedulerService.get_missed_run("02:00", last_run, now, window_minutes=60)
    assert due is None
    assert within_window is False


def test_due_time_is_still_ahead_today_uses_yesterdays_occurrence():
    """If it's not yet 02:00 today, the most recent due time was yesterday's run."""
    now = datetime(2026, 8, 9, 1, 0)
    last_run = datetime(2026, 8, 7, 2, 0).isoformat()
    due, within_window = SchedulerService.get_missed_run("02:00", last_run, now, window_minutes=1440)
    assert due == datetime(2026, 8, 8, 2, 0)
    assert within_window is True


def test_malformed_schedule_time_is_not_a_miss():
    now = datetime(2026, 8, 9, 7, 30)
    last_run = datetime(2026, 8, 8, 2, 0).isoformat()
    due, within_window = SchedulerService.get_missed_run("not-a-time", last_run, now, window_minutes=60)
    assert due is None
    assert within_window is False


def test_malformed_last_run_is_treated_as_missed():
    now = datetime(2026, 8, 9, 2, 5)
    due, within_window = SchedulerService.get_missed_run("02:00", "not-a-timestamp", now, window_minutes=60)
    assert due == datetime(2026, 8, 9, 2, 0)
    assert within_window is True


def test_overlap_guard_blocks_a_second_start_for_the_same_file():
    service = SchedulerService()
    assert service.try_start("bulk_import.txt") is True
    assert service.try_start("bulk_import.txt") is False

    service.finish("bulk_import.txt")
    assert service.try_start("bulk_import.txt") is True


def test_overlap_guard_is_independent_per_file():
    service = SchedulerService()
    assert service.try_start("a.txt") is True
    assert service.try_start("b.txt") is True
