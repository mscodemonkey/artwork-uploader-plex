"""
Service for managing scheduled bulk import jobs.

Extracted from artwork_uploader.py to reduce file size and improve
maintainability.
"""

import threading, schedule, time
from datetime import datetime, timedelta
from typing import Dict, Callable, List, Optional, Set, Tuple
from models.bulk_schedule import BulkSchedule
from core.enums import IntervalUnit

class SchedulerService:
    """Handles scheduling of bulk import jobs.

    A bulk file can carry more than one schedule, and each schedule can
    either run daily at a fixed time or repeat every N hours/days. Every
    schedule is tracked by its own id rather than by filename, so a file
    can have any number of schedules and renaming a file does not require
    tearing down and recreating its jobs.
    """

    def __init__(self, check_interval: int = 1) -> None:
        """
        Initialize the scheduler service.

        Args:
            check_interval: Seconds between scheduler checks (default: 1)
        """
        self.check_interval = check_interval
        self.scheduler_thread: Optional[threading.Thread] = None
        self.scheduled_jobs: Dict[str, schedule.Job] = {}
        # job_id -> {"file": str, "time": str} or {"file": str, "interval_value": int, "interval_unit": str}
        self.schedule_meta: Dict[str, Dict] = {}
        self.is_running = False
        self._running_lock = threading.Lock()
        self._running_files: Set[str] = set()

    def add_schedule(self, sched: BulkSchedule, callback: Callable[[str], None]) -> str:
        """
        Add a new scheduled job, either a daily time or a repeating interval.

        Args:
            filename: Name of the bulk file to process
            callback: Function to call with filename when job runs
            schedule_id: Reuse this id instead of generating one (used when
                restoring schedules from config on load)
            time: Time of day to run daily (e.g., "14:30"). Mutually
                exclusive with interval_value/interval_unit.
            interval_value: Repeat every this many hours/days. Requires
                interval_unit.
            interval_unit: "hours" or "days".

        Returns:
            Unique job ID for this schedule

        Raises:
            ValueError: If neither a time nor a valid interval is given
        """
        job_id = sched.id
        status = getattr(sched, "last_run_status", None) or "never_run"

        # The callback reads the filename from schedule_meta at run time
        # (rather than capturing it in the closure) so that renaming a
        # file only needs to update the metadata, not the underlying job.
        def run_job(job_id=job_id):
            meta = self.schedule_meta.get(job_id)
            if meta:
                callback(meta["file"])

        if sched.time:
            job = schedule.every().day.at(sched.time).do(run_job)
            sched.next_run = job.next_run.isoformat()
            meta = {
                "file": sched.file,
                "time": sched.time,
                "last_run": sched.last_run,
                "next_run": sched.next_run,
                "last_run_status": status
            }

        elif sched.interval_value and sched.interval_unit in [u.value for u in IntervalUnit]:
            interval_job = getattr(schedule.every(sched.interval_value), sched.interval_unit)
            job = interval_job.do(run_job)
            if sched.next_run:
                try:
                    job.next_run = datetime.fromisoformat(sched.next_run)
                except (ValueError, TypeError):
                    pass
            else:
                sched.next_run = job.next_run
            meta = {
                "file": sched.file,
                "interval_value": sched.interval_value,
                "interval_unit": sched.interval_unit,
                "last_run": sched.last_run,
                "next_run": sched.next_run,
                "last_run_status": status
            }

        else:
            raise ValueError("A schedule needs either a daily time or an interval_value with a valid interval_unit")

        if sched.last_run:
            job.last_run = datetime.fromisoformat(sched.last_run)

        self.scheduled_jobs[job_id] = job
        self.schedule_meta[job_id] = meta

        return job_id

    def remove_schedule(self, job_id: str) -> bool:
        """
        Remove a scheduled job.

        Args:
            job_id: Job ID to remove

        Returns:
            True if job was removed, False if not found
        """
        if job_id not in self.scheduled_jobs:
            return False

        schedule.cancel_job(self.scheduled_jobs[job_id])

        del self.scheduled_jobs[job_id]
        self.schedule_meta.pop(job_id, None)

        return True

    def get_jobs_for_file(self, filename: str) -> List[str]:
        """
        Get every job ID scheduled against a file.

        Args:
            filename: Filename to look up

        Returns:
            List of job IDs (possibly empty)
        """
        return [job_id for job_id, meta in self.schedule_meta.items() if meta["file"] == filename]

    def rename_file(self, old_filename: str, new_filename: str) -> List[str]:
        """
        Point every schedule for old_filename at new_filename instead.

        Because the callback reads the filename from schedule_meta at run
        time, this is enough to keep the schedules working - the
        underlying jobs never need to be cancelled and recreated.

        Args:
            old_filename: Filename the schedules currently reference
            new_filename: Filename they should reference instead

        Returns:
            List of job IDs that were updated
        """
        job_ids = self.get_jobs_for_file(old_filename)
        for job_id in job_ids:
            self.schedule_meta[job_id]["file"] = new_filename
        return job_ids

    def start(self) -> bool:
        """
        Start the scheduler thread.

        Returns:
            True if started, False if already running
        """
        if self.scheduler_thread is None or not self.scheduler_thread.is_alive():
            self.is_running = True
            self.scheduler_thread = threading.Thread(
                target=self._run_scheduler,
                daemon=True
            )
            self.scheduler_thread.start()
            return True
        return False

    def stop(self) -> None:
        """Stop the scheduler thread."""
        self.is_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=2)

    def _run_scheduler(self) -> None:
        """Internal method that runs in the scheduler thread."""
        while self.is_running:
            schedule.run_pending()
            time.sleep(self.check_interval)

    def clear_all_schedules(self) -> None:
        """Clear all scheduled jobs."""
        schedule.clear()
        self.scheduled_jobs.clear()
        self.schedule_meta.clear()

    def get_all_job_ids(self) -> list[str]:
        """
        Get all scheduled job IDs.

        Returns:
            List of job IDs
        """
        return list(self.scheduled_jobs.keys())

    def has_schedules(self) -> bool:
        """
        Check if there are any scheduled jobs.

        Returns:
            True if there are schedules, False otherwise
        """
        return len(self.scheduled_jobs) > 0

    def try_start(self, filename: str) -> bool:
        """
        Mark a scheduled bulk file as running, if it isn't already.

        This is the overlap guard: a catch-up run and a normally scheduled run for the
        same file must not execute at the same time.

        Args:
            filename: Bulk file the run is for

        Returns:
            True if the run was allowed to start, False if one was already in progress
        """
        with self._running_lock:
            if filename in self._running_files:
                return False
            self._running_files.add(filename)
            return True

    def finish(self, filename: str) -> None:
        """
        Mark a scheduled bulk file run as finished, releasing the overlap guard.

        Args:
            filename: Bulk file the run was for
        """
        with self._running_lock:
            self._running_files.discard(filename)

    @staticmethod
    def get_missed_run(sched: BulkSchedule, window: int) -> Tuple[Optional[datetime], bool]:
        """
        Work out whether a schedule (daily or interval) missed its most recent run.

        A run is only considered missed if we have a recorded last run time that
        predates it - a schedule with no recorded run yet is never treated as having missed anything.

        Args:
            sched: The BulkSchedule instance to check
            window: How late a missed run can be (in minutes) to still count as catchable

        Returns:
            A (due, within_window) tuple. due is None if nothing was missed.
            within_window is True if the miss is inside the catch-up window.
        """
        now = datetime.now()

        if not sched.last_run:
            return None, False

        try:
            last_run_at = datetime.fromisoformat(sched.last_run)
        except (ValueError, TypeError):
            return None, False

        due: Optional[datetime] = None

        if sched.time:
            try:
                hour, minute = (int(part) for part in sched.time.split(":"))
                due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if due > now:
                    due -= timedelta(days=1)
            except (ValueError, AttributeError, TypeError):
                return None, False

        elif sched.interval_value and sched.interval_unit in IntervalUnit:
            try:
                delta = timedelta(**{sched.interval_unit: sched.interval_value})
                due = last_run_at + delta
            except (ValueError, TypeError):
                return None, False

        else:
            return None, False

        if due > now or last_run_at >= due:
            return None, False

        within_window = (now - due) <= timedelta(minutes=window)
        return due, within_window
