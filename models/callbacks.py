from dataclasses import dataclass
from typing import Optional, Callable

@dataclass
class ProcessingCallbacks:
    """
    Callbacks for UI updates during artwork processing.

    All callbacks are optional and called with appropriate arguments
    when processing events occur.
    """
    on_status_update: Optional[Callable[[str, str, bool, bool], None]] = None  # (message, color, spinner, sticky)
    on_log_update: Optional[Callable[[str], None]] = None  # (message)
    on_progress_update: Optional[Callable[[int, int, str, str, str], None]] = None  # (current, total, title, bar type, bar speed) - for progress bars
    on_debug: Optional[Callable[[str, Optional[str]], None]] = None  # (message, context) - for debug messages
    success_counter: Optional[list] = None  # Mutable list to track successful uploads (contains count as single element)
    assets_processed: Optional[list] = None  # Mutable list to track total assets processed (contains count as single element)

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