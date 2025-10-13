"""
Service for managing scheduled bulk import jobs.

Extracted from artwork_uploader.py to reduce file size and improve
maintainability.
"""

from typing import Dict, Callable, Optional
import threading
import schedule
import time
import uuid


class SchedulerService:
    """Handles scheduling of bulk import jobs."""

    def __init__(self, check_interval: int = 1) -> None:
        """
        Initialize the scheduler service.

        Args:
            check_interval: Seconds between scheduler checks (default: 1)
        """
        self.check_interval = check_interval
        self.scheduler_thread: Optional[threading.Thread] = None
        self.scheduled_jobs: Dict[str, schedule.Job] = {}
        self.scheduled_jobs_by_file: Dict[str, str] = {}
        self.is_running = False

    def add_schedule(
        self,
        filename: str,
        schedule_time: str,
        callback: Callable[[str], None]
    ) -> str:
        """
        Add a new scheduled job.

        Args:
            filename: Name of the bulk file to process
            schedule_time: Time to run (e.g., "14:30")
            callback: Function to call with filename when job runs

        Returns:
            Unique job ID for this schedule
        """
        # Create the scheduled job
        job = schedule.every().day.at(schedule_time).do(
            lambda: callback(filename)
        )

        # Create a unique job ID
        job_id = str(uuid.uuid4())

        # Store job references
        self.scheduled_jobs[job_id] = job
        self.scheduled_jobs_by_file[filename] = job_id

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

        # Get the job
        job = self.scheduled_jobs[job_id]

        # Remove from schedule library
        schedule.cancel_job(job)

        # Remove from our tracking dicts
        del self.scheduled_jobs[job_id]

        # Remove from file lookup (find which file maps to this job_id)
        file_to_remove = None
        for filename, jid in self.scheduled_jobs_by_file.items():
            if jid == job_id:
                file_to_remove = filename
                break
        if file_to_remove:
            del self.scheduled_jobs_by_file[file_to_remove]

        return True

    def get_job_id_by_file(self, filename: str) -> Optional[str]:
        """
        Get the job ID for a scheduled file.

        Args:
            filename: Filename to look up

        Returns:
            Job ID if found, None otherwise
        """
        return self.scheduled_jobs_by_file.get(filename)

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
        self.scheduled_jobs_by_file.clear()

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
