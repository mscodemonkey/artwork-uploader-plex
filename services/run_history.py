"""
Persistent record of what the tool has done.

A small JSON file (in the config directory) that keeps one entry per run, whatever
started it: a bulk import file run manually or by a schedule, a single URL scraped
from the main tab, an artwork ZIP uploaded through the browser, or a Radarr/Sonarr
import applied by the webhook. Container logs rotate; this is what answers "did last
night's run actually do anything" without needing them.
"""

import json
import os
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from core.enums import RunType, RunTrigger
from core import globals

from core.constants import RUN_HISTORY_PATH, RUN_HISTORY_MAX_ENTRIES, RUN_HISTORY_MAX_AGE_DAYS, DEFAULT_LOG_PATH

# A new RunHistory() is created per call rather than shared, so the read-modify-write in
# add_run needs a lock keyed by file path (not an instance lock) to stop two runs finishing
# at the same time - e.g. a schedule firing while a webhook applies a new import - from
# each loading the same list and one overwriting the other's record.
_write_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)


class RunHistory:
    """
    Append-only log of runs, capped by both count and age so it cannot grow without
    limit. Readers and writers each open the file for the duration of the call, matching
    the short-lived-connection approach used by AssetIndex; writes are serialized per path
    so two runs finishing at once can't clobber each other.
    """

    def __init__(
        self,
        path: str = RUN_HISTORY_PATH,
        max_entries: int = RUN_HISTORY_MAX_ENTRIES,
        max_age_days: int = RUN_HISTORY_MAX_AGE_DAYS,
    ) -> None:
        self.path = path
        self.max_entries = max_entries
        self.max_age_days = max_age_days

    def _load(self) -> List[Dict[str, Any]]:
        if not os.path.isfile(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as history_file:
                runs = json.load(history_file)
            return runs if isinstance(runs, list) else []
        except (OSError, json.JSONDecodeError) as e:
            # Lazily imported: utils.notifications pulls in the services package, and this
            # module is imported from services/__init__.py, so a top-level import would cycle.
            from utils.notifications import debug_me
            debug_me(f"Run history at '{self.path}' could not be read, starting fresh: {e}")
            return []

    def _save(self, runs: List[Dict[str, Any]]) -> None:
        # Written to a temporary file and moved into place, so a reader never sees a partly
        # written one. The write lock above only holds within a single process, and a bulk
        # import run from the command line is a second process alongside the web interface,
        # so a read landing mid-write is possible: it would come back empty and the next
        # save would keep only its own record. os.replace is atomic on POSIX and Windows.
        temp_path = f"{self.path}.tmp"
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(temp_path, "w", encoding="utf-8") as history_file:
                json.dump(runs, history_file, indent=4)
            os.replace(temp_path, self.path)
        except OSError as e:
            from utils.notifications import debug_me
            debug_me(f"Run history could not be saved to '{self.path}': {e}")
            try:
                os.remove(temp_path)
            except OSError:
                pass  # nothing to tidy up, or the same problem that stopped the write

    def _prune(self, runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        pruned_runs = []
        if self.max_age_days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=self.max_age_days)).isoformat()
            pruned_runs = [run for run in runs if run.get("started_at", "") < cutoff]
            runs = [run for run in runs if run.get("started_at", "") >= cutoff]
        if self.max_entries:
            # The count cap is per run type. A busy library can take dozens of webhook
            # imports a day, and a single shared cap would push a nightly bulk import out
            # of the history within the week - the run people most want to look back at.
            kept_per_type: Dict[str, int] = defaultdict(int)
            kept: List[Dict[str, Any]] = []
            for run in reversed(runs):
                run_type = run.get("run_type", RunType.BULK.value)
                if kept_per_type[run_type] >= self.max_entries:
                    pruned_runs.append(run)
                    continue
                kept_per_type[run_type] += 1
                kept.append(run)
            runs = list(reversed(kept))
        # Delete the log files for the pruned runs
        for run in pruned_runs:
            log_file = run.get("log_file", "")
            if log_file:
                full_path = os.path.join(DEFAULT_LOG_PATH, log_file)
                try:
                    os.remove(full_path)
                    debug_me(f"Deleted log file '{log_file}'")
                except Exception as e:
                    from utils.notifications import debug_me
                    debug_me(f"Unable to remove log file '{log_file}': {str(e)}")
                    pass
        return runs

    def add_run(
        self,
        run_type: str,
        label: str,
        started_at: str,
        ended_at: str,
        trigger: str,
        outcome: str,
        assets_processed: int = 0,
        success_count: int = 0,
        cached_count: int = 0,
        locked_count: int = 0,
        error_count: int = 0,
        job_id: Optional[str] = None
    ) -> None:
        """Append a record for one completed (or skipped/failed) run.

        `label` is what the run was about: the bulk file name, the scraped URL, the
        uploaded ZIP name, or the title the webhook imported."""
        with _write_locks[os.path.abspath(self.path)]:
            runs = self._load()
            runs.append({
                "run_type": run_type,
                "label": label,
                "started_at": started_at,
                "ended_at": ended_at,
                "trigger": trigger,
                "outcome": outcome,
                "assets_processed": assets_processed,
                "success_count": success_count,
                "cached_count": cached_count,
                "locked_count": locked_count,
                "error_count": error_count,
                "log_file": os.path.basename(globals.log_to_file) if globals.log_to_file else ""
            })
            self._save(self._prune(runs))
        globals.log_to_file = None # Stop persistent logging after a run is recorded
        if job_id and globals.scheduler_service:
            job_meta = globals.scheduler_service.schedule_meta.get(job_id)
            if job_meta:
                job_meta["last_run_status"] = outcome
            if globals.config:
                globals.config.load()
                schedules = globals.config.schedules
                if schedules:
                    for schedule in schedules:
                        if schedule["id"] == job_id:
                            schedule["last_run_status"] = outcome
                globals.config.save()

    @staticmethod
    def _normalise(run: Dict[str, Any]) -> Dict[str, Any]:
        """Fill in the fields a record written by an older version doesn't carry, so an
        existing history file keeps rendering. Those records were all bulk imports and
        held the file name as `filename` and the trigger as a `scheduled` boolean."""
        normalised = dict(run)
        if not normalised.get("run_type"):
            normalised["run_type"] = RunType.BULK.value
        if not normalised.get("label"):
            normalised["label"] = run.get("filename", "")
        if not normalised.get("trigger"):
            normalised["trigger"] = RunTrigger.SCHEDULED.value if run.get("scheduled") else RunTrigger.MANUAL.value
        return normalised

    def get_runs(self, limit: Optional[int] = None, run_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Most recent runs first, optionally narrowed to one run type and capped to `limit`.

        The type filter is applied before the limit, so asking for bulk imports returns the
        last `limit` bulk imports rather than the bulk imports among the last `limit` runs."""
        runs = [self._normalise(run) for run in reversed(self._load())]
        if run_type:
            runs = [run for run in runs if run["run_type"] == run_type]
        if limit:
            runs = runs[:limit]
        return runs
