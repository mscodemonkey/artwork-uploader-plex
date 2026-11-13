from dataclasses import dataclass, field
from typing import Optional, Callable, Dict

from core.enums import RunOutcome

@dataclass
class ProcessingCallbacks:
    """
    Callbacks for UI updates during artwork processing, and the tally of what the run did.

    All callbacks are optional and called with appropriate arguments
    when processing events occur.

    The counters are always present, so a caller that forgets one still gets a working
    counter rather than a number that stays at zero.
    """
    on_status_update: Optional[Callable[[str, str, bool, bool], None]] = None  # (message, color, spinner, sticky)
    on_log_update: Optional[Callable[[str], None]] = None  # (message)
    on_progress_update: Optional[Callable[[int, int, str, str, str], None]] = None  # (current, total, title, bar type, bar speed) - for progress bars
    on_debug: Optional[Callable[[str, Optional[str]], None]] = None  # (message, context) - for debug messages
    success_counter: list = field(default_factory=lambda: [0])  # Mutable list to track successful uploads (contains count as single element)
    assets_processed: list = field(default_factory=lambda: [0])  # Mutable list to track total assets processed (contains count as single element)
    cached_counter: list = field(default_factory=lambda: [0])  # Mutable list to track assets newly added to the user cache (contains count as single element)
    locked_counter: list = field(default_factory=lambda: [0])  # Mutable list to track artwork skipped because the Plex field was locked (contains count as single element)
    failed_counter: list = field(default_factory=lambda: [0])  # Mutable list to track uploads that failed after exhausting their retries (contains count as single element)
    unavailable_counter: list = field(default_factory=lambda: [0]) # Mutable list to track items that are not available in Plex
    updated_asset_map: Dict[str, Dict[int, str]] = field(default_factory=dict)

    def status(self, message: str, color: str = "info", spinner: bool = False, sticky: bool = False):
        if self.on_status_update:
            self.on_status_update(message, color, spinner, sticky)

    def log(self, message: str):
        if self.on_log_update:
            self.on_log_update(message)

    def debug(self, message: str, context: Optional [str] = None):
        if self.on_debug:
            self.on_debug(message, context)

    def progress(self, current: int, total: int, title: str = None, bar_type: str = "main", bar_speed: str = "smooth"):
        if self.on_progress_update:
            self.on_progress_update(current, total, title, bar_type, bar_speed)

    def success(self, count: int):
        if self.success_counter:
            self.success_counter[0] += count

    def assets(self, count: int):
        if self.assets_processed:
            self.assets_processed[0] += count

    def cached(self, count: int):
        if self.cached_counter:
            self.cached_counter[0] += count

    def locked(self, count: int):
        if self.locked_counter:
            self.locked_counter[0] += count

    def failed(self, count: int):
        if self.failed_counter:
            self.failed_counter[0] += count

    def unavailable(self, count: int):
        if self.unavailable_counter:
            self.unavailable_counter[0] += count

    def record_result(self, result: str, artwork: Dict = None) -> Optional[str]:
        """Count one upload result and say what it was.

        The uploader and the Kometa saver both report what happened as a prefixed
        string, so the prefixes are the only record of an item's fate. Every caller
        that tallies a run reads them here, so they are written down once."""
        self.assets(1)
        if result.startswith('✅') or result.startswith('♻️'):
            self.success(1)
            if artwork:
                library = artwork.get('library', None)
                ratingKey = artwork.get('ratingKey', 0)
                parent_key = artwork.get("parent_key", None)
                title = artwork.get('title', '')
                alt_title = artwork.get('alt_title', None)
                year = artwork.get('year', None)
                media_type = artwork.get('media_type', '')
                overlay = artwork.get('overlay', False)
                season = artwork.get('season', None)
                from utils.utils import is_numeric
                if is_numeric(season):
                    season = int(season)
                episode = artwork.get('episode', None)
                if is_numeric(episode):
                    episode = int(episode)
                if ratingKey and library:
                    if library not in self.updated_asset_map:
                        self.updated_asset_map[library] = {}
                    if ratingKey not in self.updated_asset_map[library]:
                        self.updated_asset_map[library][ratingKey] = {}
                    self.updated_asset_map[library][ratingKey]["title"] = title
                    self.updated_asset_map[library][ratingKey]["year"] = year
                    self.updated_asset_map[library][ratingKey]["media_type"] = media_type
                    if parent_key:
                        self.updated_asset_map[library][ratingKey]["parent_key"] = parent_key
                    if alt_title:
                        self.updated_asset_map[library][ratingKey]["alt_title"] = alt_title
                    if "updated_assets" not in self.updated_asset_map[library][ratingKey]:
                        self.updated_asset_map[library][ratingKey]["updated_assets"] = []
                    self.updated_asset_map[library][ratingKey]["updated_assets"].append({
                        "file_type": artwork["file_type"],
                        "author": artwork["author"],
                        "season": season,
                        "episode": episode,
                        "overlay": overlay,
                        "status": artwork.get("status", "")
                    })
            return "success"
        if result.startswith('🔒'):
            self.locked(1)
            return "locked"
        if result.startswith('❌'):
            self.failed(1)
            return "failed"
        if "not available" in str(result).lower():
            self.unavailable(1)
            return "unavailable"
        return None

    def errors(self, extra: int = 0) -> int:
        """Every failure the run summary counts.

        An upload that exhausted its retries, plus anything the caller counted itself.
        An item that succeeded on a retry never reaches failed_counter, so it is not one.

        Args:
            extra: Failures counted outside the uploader, such as a bulk import line
                that could not be scraped at all.
        """
        return (self.failed_counter[0] if self.failed_counter else 0) + extra

    def outcome(self, stopped: bool = False, extra_errors: int = 0) -> str:
        """Say how a run ended, from the counters it collected.

        Written down here because the paths that record a run each decided this for
        themselves, and they had already drifted: a bulk import from the Bulk Import
        tab had no skipped branch, so a file that processed nothing was stored as a
        success while the same file from the scrape tab, a ZIP or the command line was
        stored as skipped.

        Args:
            stopped: True if the user pressed Stop. Only the paths with a Stop button
                pass this, so a run started from the command line never reports stopped.
            extra_errors: Passed on to errors().
        """
        if stopped:
            return RunOutcome.STOPPED.value
        if self.errors(extra_errors):
            return RunOutcome.PARTIAL.value
        if self.assets_processed and self.assets_processed[0]:
            return RunOutcome.SUCCESS.value
        return RunOutcome.SKIPPED.value
