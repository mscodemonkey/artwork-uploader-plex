"""
Service for checking application updates from GitHub.

Extracted from artwork_uploader.py to reduce file size and improve
maintainability.
"""

import threading
import time
from typing import Optional, Callable

import requests
from packaging import version
from utils.notifications import debug_me


class UpdateService:
    """Handles checking for application updates from GitHub."""

    def __init__(
            self,
            github_repo: str,
            current_version: str,
            check_interval: int = 3600
    ) -> None:
        """
        Initialize the update service.

        Args:
            github_repo: GitHub repository (e.g., "user/repo")
            current_version: Current version of the application
            check_interval: Seconds between update checks (default: 3600 = 1 hour)
        """
        self.github_repo = github_repo
        self.current_version = current_version
        self.check_interval = check_interval
        self.update_thread: Optional[threading.Thread] = None
        self.is_running = False

    def get_latest_version(self) -> Optional[str]:
        """
        Fetch the latest release version from GitHub.

        Returns:
            Latest version tag if found, None otherwise
        """
        url = f"https://api.github.com/repos/{self.github_repo}/releases/latest"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()["tag_name"]
            else:
                debug_me(f"Failed to fetch latest version. GitHub API returned status code: {response.status_code}",
                         "UpdateService/get_latest_version")
        except Exception:
            pass
        return None

    def check_for_update(self) -> Optional[str]:
        """
        Check if a newer version is available.

        Returns:
            New version string if available, None if up to date or check failed
        """
        latest_version = self.get_latest_version()
        if latest_version:
            # Normalize versions by removing 'v' prefix for comparison
            latest_normalized = latest_version.lstrip('v')
            current_normalized = self.current_version.lstrip('v')

            if version.parse(latest_normalized) > version.parse(current_normalized):
                debug_me(f"Update available! Current version: {self.current_version}. Latest version: {latest_version}",
                         "UpdateService/check_for_update")
                return latest_version
            else:
                debug_me(f"No update available.", "UpdateService/check_for_update")
        else:
            debug_me("Could not determine latest version.", "UpdateService/check_for_update")
        return None

    def start_periodic_check(
            self,
            on_update_available: Callable[[str], None]
    ) -> bool:
        """
        Start periodic update checking in a background thread.

        Args:
            on_update_available: Callback function called with version string
                                when update is available

        Returns:
            True if started, False if already running
        """
        if self.update_thread is None or not self.update_thread.is_alive():
            self.is_running = True
            self.update_thread = threading.Thread(
                target=self._check_periodically,
                args=(on_update_available,),
                daemon=True
            )
            self.update_thread.start()
            return True
        return False

    def stop_periodic_check(self) -> None:
        """Stop the periodic update checking."""
        self.is_running = False
        if self.update_thread:
            self.update_thread.join(timeout=2)

    def _check_periodically(
            self,
            on_update_available: Callable[[str], None]
    ) -> None:
        """
        Internal method that runs in the update checking thread.

        Args:
            on_update_available: Callback function for update notifications
        """
        while self.is_running:
            new_version = self.check_for_update()
            if new_version:
                on_update_available(new_version)
            debug_me(f"Next update check in {self.check_interval} seconds.", "UpdateService/_check_periodically")
            time.sleep(self.check_interval)
