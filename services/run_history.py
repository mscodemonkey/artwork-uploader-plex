"""
Persistent record of bulk import runs.

A small JSON file (in the config directory) that keeps one entry per run of a bulk
import file, whether that run was triggered manually from the web UI or by a schedule.
Container logs rotate; this is what answers "did last night's run actually do
anything" without needing them.
"""

import json
import os
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.constants import RUN_HISTORY_PATH, RUN_HISTORY_MAX_ENTRIES, RUN_HISTORY_MAX_AGE_DAYS

# Recorded outcomes for a run
OUTCOME_SUCCESS = "success"
OUTCOME_PARTIAL = "partial"    # completed, but one or more URLs errored
OUTCOME_STOPPED = "stopped"    # cancelled by the user
OUTCOME_FAILED = "failed"      # an exception aborted the run
OUTCOME_SKIPPED = "skipped"    # nothing to do (e.g. no valid entries in the file)

# A new RunHistory() is created per call rather than shared, so the read-modify-write in
# add_run needs a lock keyed by file path (not an instance lock) to stop two runs finishing
# at the same time - e.g. a schedule firing while a manual run is still in progress - from
# each loading the same list and one overwriting the other's record.
_write_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)


class RunHistory:
    """
    Append-only log of bulk import runs, capped by both count and age so it cannot
    grow without limit. Readers and writers each open the file for the duration of
    the call, matching the short-lived-connection approach used by AssetIndex; writes
    are serialized per path so two runs finishing at once can't clobber each other.
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
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as history_file:
                json.dump(runs, history_file, indent=4)
        except OSError as e:
            from utils.notifications import debug_me
            debug_me(f"Run history could not be saved to '{self.path}': {e}")

    def _prune(self, runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if self.max_age_days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=self.max_age_days)).isoformat()
            runs = [run for run in runs if run.get("started_at", "") >= cutoff]
        if self.max_entries and len(runs) > self.max_entries:
            runs = runs[-self.max_entries:]
        return runs

    def add_run(
        self,
        filename: str,
        started_at: str,
        ended_at: str,
        scheduled: bool,
        outcome: str,
        assets_processed: int = 0,
        success_count: int = 0,
        cached_count: int = 0,
        locked_count: int = 0,
        error_count: int = 0,
    ) -> None:
        """Append a record for one completed (or skipped/failed) run."""
        with _write_locks[os.path.abspath(self.path)]:
            runs = self._load()
            runs.append({
                "filename": filename,
                "started_at": started_at,
                "ended_at": ended_at,
                "scheduled": scheduled,
                "outcome": outcome,
                "assets_processed": assets_processed,
                "success_count": success_count,
                "cached_count": cached_count,
                "locked_count": locked_count,
                "error_count": error_count,
            })
            self._save(self._prune(runs))

    def get_runs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Most recent runs first, optionally capped to `limit`."""
        runs = list(reversed(self._load()))
        if limit:
            runs = runs[:limit]
        return runs
