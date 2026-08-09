"""
Application configuration management.
"""

import json, os, uuid
from core import globals
from typing import List, Dict, Any
from core.constants import (
    DEFAULT_PLEX_CONNECT_TIMEOUT,
    DEFAULT_KOMETA_DOWNLOAD_TIMEOUT,
    DEFAULT_UPLOAD_RETRY_ATTEMPTS,
    DEFAULT_UPLOAD_RETRY_BACKOFF_SECONDS,
    DEFAULT_NOTIFICATION_EVENTS
)
from core.exceptions import ConfigLoadError, ConfigSaveError, ConfigCreationError
from utils.notifications import debug_me
from utils.utils import get_host_path


def normalize_notification_channels(apprise_urls: List[Any]) -> List[Dict[str, Any]]:
    """
    Normalize the apprise_urls config entry into a list of {"url", "events"} channels.

    Older config files store apprise_urls as a bare list of URL strings, with every
    configured channel receiving every notification. Those are migrated here to
    channels subscribed to DEFAULT_NOTIFICATION_EVENTS, which matches what they
    actually received before per-event routing existed, so upgrading does not
    suddenly start sending more than before.
    """
    channels = []
    for entry in apprise_urls or []:
        if isinstance(entry, dict):
            url = entry.get("url", "")
            if not url:
                continue
            events = entry.get("events", DEFAULT_NOTIFICATION_EVENTS)
            if not isinstance(events, list):
                events = DEFAULT_NOTIFICATION_EVENTS
            channels.append({"url": url, "events": list(events)})
        elif isinstance(entry, str):
            if entry:
                channels.append({"url": entry, "events": list(DEFAULT_NOTIFICATION_EVENTS)})
    return channels


class Config:
    """
    Manages application configuration stored in JSON format.

    Attributes:
        path: Path to the configuration file
        base_url: Plex server URL
        token: Plex authentication token
        bulk_txt: Default bulk import filename
        tv_library: List of TV library names in Plex
        movie_library: List of movie library names in Plex
        mediux_filters: Default filters for MediUX scraping
        tpdb_filters: Default filters for ThePosterDB scraping
        kometa_base: Base directory for Kometa asset storage
        temp_dir: (Optional) Temporary directory for testing purposes
        save_to_kometa: Whether to save artwork to Kometa
        stage_assets: Whether to download assets for seasons and episodes that are not in Plex yet (except Specials)
        track_artwork_ids: Whether to track artwork IDs using Plex labels
        skip_locked_artwork: Whether to skip artwork whose target field is locked in Plex (already set)
        local_library_matching: Whether to match scraped artwork against the local libraries before fetching poster pages
        allow_artist_updates: Whether to update locked artwork we applied when the same artist has posted a newer version (requires skip_locked_artwork and track_artwork_ids)
        cache_user_scrapes: Whether to keep a persistent index of ThePosterDB users' uploads so repeat scrapes only fetch new ones
        user_cache_refresh_days: Days between full re-crawls of a cached user's uploads (catches edits and deletions)
        auto_manage_bulk_files: Whether to auto-organize bulk files
        reset_overlay: Whether to reset Kometa overlay labels on upload
        schedules: List of scheduled bulk import jobs
        catch_up_window_minutes: How late a missed scheduled run can be and still run on startup, in minutes (0 disables catch-up)
        auth_enabled: Whether authentication is enabled for the web server
        auth_username: Username for web server authentication
        auth_password_hash: Hashed password for web server authentication
        apprise_urls: List of notification channels, each {"url": Apprise URL, "events": list of event names the channel is subscribed to}
        enable_webhooks: Whether the Sonarr/Radarr import webhook endpoint is enabled
        webhook_token: Shared secret required on webhook requests
        webhook_tpdb_users: ThePosterDB users to apply cached artwork from on import, in priority order
        webhook_apply_delay: Seconds to wait after an import before applying artwork (lets Plex scan first)
        plex_connect_timeout: Timeout for connecting to the Plex server (also applies to uploads)
        kometa_download_timeout: Timeout for downloading artwork to save to the Kometa asset directory
        upload_retry_attempts: Total attempts (including the first) made for a transient upload failure
        upload_retry_backoff_seconds: Seconds to wait before the first retry, doubling after each attempt
    """

    def __init__(self, config_path: str = "config/config.json") -> None:
        self.path: str = config_path
        self.base_url: str = ""
        self.token: str = ""
        self.bulk_txt: str = "bulk_import.txt"
        self.tv_library: List[str] = []
        self.movie_library: List[str] = []
        self.mediux_filters: List[str] = ["title_card", "background", "season_cover", "show_cover", "movie_poster", "collection_poster"]
        self.tpdb_filters: List[str] = ["season_cover", "show_cover", "movie_poster", "collection_poster"]
        self.kometa_base: str = ""
        self.temp_dir: str = ""
        self.save_to_kometa: bool = False
        self.stage_assets: bool = False
        self.track_artwork_ids: bool = True
        self.skip_locked_artwork: bool = False
        self.local_library_matching: bool = False
        self.allow_artist_updates: bool = False
        self.cache_user_scrapes: bool = False
        self.user_cache_refresh_days: int = 7
        self.auto_manage_bulk_files: bool = True
        self.reset_overlay: bool = False
        self.schedules: List[Dict[str, Any]] = []
        self.catch_up_window_minutes: int = 0
        self.auth_enabled: bool = False
        self.auth_username: str = ""
        self.auth_password_hash: str = ""
        self.apprise_urls: List[Dict[str, Any]] = []
        self.enable_webhooks: bool = False
        self.webhook_token: str = ""
        self.webhook_tpdb_users: List[str] = []
        self.webhook_apply_delay: int = 30
        self.plex_connect_timeout: int = DEFAULT_PLEX_CONNECT_TIMEOUT
        self.kometa_download_timeout: int = DEFAULT_KOMETA_DOWNLOAD_TIMEOUT
        self.upload_retry_attempts: int = DEFAULT_UPLOAD_RETRY_ATTEMPTS
        self.upload_retry_backoff_seconds: float = DEFAULT_UPLOAD_RETRY_BACKOFF_SECONDS


    def load(self) -> None:
        """Load the configuration from the JSON file."""

        # If a config file doesn't exist, create one with default values
        if not os.path.isfile(self.path):
            self.create()

        # Load the configuration from the config.json file
        try:
            with open(self.path, "r", encoding="utf-8") as config_file:
                config = json.load(config_file)

            self.base_url = config.get("base_url", "")
            self.token = config.get("token", "")
            self.tv_library = config.get("tv_library", [])
            self.movie_library = config.get("movie_library", [])
            self.mediux_filters = config.get("mediux_filters", [])
            self.tpdb_filters = config.get("tpdb_filters", [])
            if globals.docker:
                self.kometa_base = get_host_path("/assets")
                self.temp_dir = get_host_path("/temp")
            else:
                self.kometa_base = config.get("kometa_base", "")
                self.temp_dir = config.get("temp_dir", "")
            self.save_to_kometa = config.get("save_to_kometa", False)
            self.stage_assets = config.get("stage_assets", True)
            self.bulk_txt = config.get("bulk_txt", "bulk_import.txt")
            self.track_artwork_ids = config.get("track_artwork_ids", True)
            self.skip_locked_artwork = config.get("skip_locked_artwork", False)
            self.local_library_matching = config.get("local_library_matching", False)
            self.allow_artist_updates = config.get("allow_artist_updates", False)
            self.cache_user_scrapes = config.get("cache_user_scrapes", False)
            self.user_cache_refresh_days = config.get("user_cache_refresh_days", 7)
            self.auto_manage_bulk_files = config.get("auto_manage_bulk_files", True)
            self.reset_overlay = config.get("reset_overlay", False)
            self.schedules, schedules_migrated = self._migrate_schedules(config.get("schedules", []))
            self.catch_up_window_minutes = config.get("catch_up_window_minutes", 0)
            self.auth_enabled = config.get("auth_enabled", False)
            self.auth_username = config.get("auth_username", "")
            self.auth_password_hash = config.get("auth_password_hash", "")
            self.apprise_urls = normalize_notification_channels(config.get("apprise_urls", []))
            self.enable_webhooks = config.get("enable_webhooks", False)
            self.webhook_token = config.get("webhook_token", "")
            self.webhook_tpdb_users = config.get("webhook_tpdb_users", [])
            self.webhook_apply_delay = config.get("webhook_apply_delay", 30)
            self.plex_connect_timeout = config.get("plex_connect_timeout", DEFAULT_PLEX_CONNECT_TIMEOUT)
            self.kometa_download_timeout = config.get("kometa_download_timeout", DEFAULT_KOMETA_DOWNLOAD_TIMEOUT)
            self.upload_retry_attempts = config.get("upload_retry_attempts", DEFAULT_UPLOAD_RETRY_ATTEMPTS)
            self.upload_retry_backoff_seconds = config.get("upload_retry_backoff_seconds", DEFAULT_UPLOAD_RETRY_BACKOFF_SECONDS)

        except Exception as e:
            raise ConfigLoadError(f"Error loading configuration from '{self.path}': {e}") from e

        # Persist any ids minted by the migration above, so they stay stable
        # across reloads instead of being handed out fresh every time (which
        # would break anything that had already matched a schedule by id).
        if schedules_migrated:
            self.save()

    @staticmethod
    def _migrate_schedules(schedules: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], bool]:
        """
        Give every schedule an id, so schedules are addressed by their own
        id rather than by filename.

        Older config.json files stored one schedule per file as
        {"file": ..., "time": ...} with no id. Those entries keep working
        unchanged, they just gain an id here so they can sit alongside
        other schedules on the same file.

        Returns:
            The schedule list, and whether any entry was missing an id
        """
        migrated = False
        for entry in schedules:
            if "id" not in entry:
                entry["id"] = str(uuid.uuid4())
                migrated = True
        return schedules, migrated

    def create(self) -> None:
        """Create a new configuration file with default values."""
        config_json = {
            "base_url": "",
            "token": "",
            "bulk_txt": "bulk_import.txt",
            "tv_library": [],
            "movie_library": [],
            "mediux_filters": ["title_card", "background", "season_cover", "show_cover", "movie_poster", "collection_poster", "square_art"],
            "tpdb_filters": ["season_cover", "show_cover", "movie_poster", "collection_poster"],
            "kometa_base": "",
            "temp_dir": "",
            "save_to_kometa": False,
            "stage_assets": False,
            "track_artwork_ids": True,
            "skip_locked_artwork": False,
            "local_library_matching": False,
            "allow_artist_updates": False,
            "cache_user_scrapes": False,
            "user_cache_refresh_days": 7,
            "auto_manage_bulk_files": True,
            "reset_overlay": True,
            "schedules": [],
            "catch_up_window_minutes": 0,
            "apprise_urls": [],
            "enable_webhooks": False,
            "webhook_token": "",
            "webhook_tpdb_users": [],
            "webhook_apply_delay": 30,
            "plex_connect_timeout": DEFAULT_PLEX_CONNECT_TIMEOUT,
            "kometa_download_timeout": DEFAULT_KOMETA_DOWNLOAD_TIMEOUT,
            "upload_retry_attempts": DEFAULT_UPLOAD_RETRY_ATTEMPTS,
            "upload_retry_backoff_seconds": DEFAULT_UPLOAD_RETRY_BACKOFF_SECONDS
        }

        if globals.docker:
            host_kometa_base = get_host_path("/assets")
            config_json["kometa_base"] = host_kometa_base if host_kometa_base != "(not defined)" else ""
            host_temp_dir = get_host_path("/temp")
            config_json["temp_dir"] = host_temp_dir if host_temp_dir != "(not defined)" else ""

        # Create the config.json file if it doesn't exist
        if not os.path.isfile(self.path):
            try:
                with open(self.path, "w", encoding="utf-8") as config_file:
                    json.dump(config_json, config_file, indent=4)
                debug_me(f"Config file '{self.path}' created with default settings.")
            except Exception as e:
                raise ConfigCreationError(f"Error creating configuration file as '{self.path}': {e}") from e

    def save(self) -> None:
        """Save the current configuration to the file."""

        for schedule in self.schedules:
            schedule.pop("jobReference", None)

        config_json = {
            "base_url": self.base_url,
            "token": self.token,
            "tv_library": self.tv_library,
            "movie_library": self.movie_library,
            "mediux_filters": self.mediux_filters,
            "tpdb_filters": self.tpdb_filters,
            "kometa_base": self.kometa_base,
            "temp_dir": self.temp_dir,
            "save_to_kometa": self.save_to_kometa,
            "stage_assets": self.stage_assets,
            "bulk_txt": self.bulk_txt,
            "track_artwork_ids": self.track_artwork_ids,
            "skip_locked_artwork": self.skip_locked_artwork,
            "local_library_matching": self.local_library_matching,
            "allow_artist_updates": self.allow_artist_updates,
            "cache_user_scrapes": self.cache_user_scrapes,
            "user_cache_refresh_days": self.user_cache_refresh_days,
            "auto_manage_bulk_files": self.auto_manage_bulk_files,
            "reset_overlay": self.reset_overlay,
            "schedules": self.schedules,
            "catch_up_window_minutes": self.catch_up_window_minutes,
            "auth_enabled": self.auth_enabled,
            "auth_username": self.auth_username,
            "auth_password_hash": self.auth_password_hash,
            "apprise_urls": self.apprise_urls,
            "enable_webhooks": self.enable_webhooks,
            "webhook_token": self.webhook_token,
            "webhook_tpdb_users": self.webhook_tpdb_users,
            "webhook_apply_delay": self.webhook_apply_delay,
            "plex_connect_timeout": self.plex_connect_timeout,
            "kometa_download_timeout": self.kometa_download_timeout,
            "upload_retry_attempts": self.upload_retry_attempts,
            "upload_retry_backoff_seconds": self.upload_retry_backoff_seconds
        }

        try:
            with open(self.path, "w", encoding="utf-8") as config_file:
                json.dump(config_json, config_file, indent=4)
        except Exception as e:
            raise ConfigSaveError(f"Error saving configuration to '{self.path}': {e}") from e
