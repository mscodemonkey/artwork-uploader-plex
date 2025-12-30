"""
Application configuration management.
"""

import json
import os
from typing import List, Dict, Any

from core.constants import DEFAULT_CONFIG_PATH, DEFAULT_BULK_IMPORT_FILE, DEFAULT_TV_LIBRARY, DEFAULT_MOVIE_LIBRARY, DEFAULT_IP_BINDING
from core.exceptions import ConfigLoadError, ConfigSaveError, ConfigCreationError
from utils.notifications import debug_me


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
        auto_manage_bulk_files: Whether to auto-organize bulk files
        reset_overlay: Whether to reset Kometa overlay labels on upload
        schedules: List of scheduled bulk import jobs
        auth_enabled: Whether authentication is enabled for the web server
        auth_username: Username for web server authentication
        auth_password_hash: Hashed password for web server authentication
        ip_binding: IP binding mode - "auto" (default), "ipv4", or "ipv6"
    """

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH) -> None:
        self.path: str = config_path
        self.base_url: str = ""
        self.token: str = ""
        self.bulk_txt: str = DEFAULT_BULK_IMPORT_FILE
        self.tv_library: List[str] = DEFAULT_TV_LIBRARY
        self.movie_library: List[str] = DEFAULT_MOVIE_LIBRARY
        self.mediux_filters: List[str] = ["title_card", "background", "season_cover", "show_cover", "movie_poster",
                                          "collection_poster"]
        self.tpdb_filters: List[str] = ["title_card", "background", "season_cover", "show_cover", "movie_poster",
                                        "collection_poster"]
        self.kometa_base: str = "C:\\Temp\\assets"
        self.temp_dir: str = "C:\\Temp\\assets\\temp"
        self.save_to_kometa: bool = False
        self.stage_assets: bool = True
        self.track_artwork_ids: bool = True
        self.auto_manage_bulk_files: bool = True
        self.reset_overlay: bool = False
        self.schedules: List[Dict[str, Any]] = []
        self.auth_enabled: bool = False
        self.auth_username: str = ""
        self.auth_password_hash: str = ""
        self.ip_binding: str = DEFAULT_IP_BINDING

    def load(self) -> None:
        """Load the configuration from the JSON file."""
        print(f"[DEBUG Config.load] Config path: {self.path}")
        print(f"[DEBUG Config.load] File exists: {os.path.isfile(self.path)}")

        # If a config file doesn't exist, create one with default values
        if not os.path.isfile(self.path):
            print(f"[DEBUG Config.load] Config file does not exist, calling create()")
            self.create()
            print(f"[DEBUG Config.load] After create(), file exists: {os.path.isfile(self.path)}")

        # Load the configuration from the config.json file
        print(f"[DEBUG Config.load] Attempting to open config file for reading")
        try:
            with open(self.path, "r", encoding="utf-8") as config_file:
                config = json.load(config_file)

            self.base_url = config.get("base_url", "")
            self.token = config.get("token", "")
            self.tv_library = config.get("tv_library", [])
            self.movie_library = config.get("movie_library", [])
            self.mediux_filters = config.get("mediux_filters", [])
            self.tpdb_filters = config.get("tpdb_filters", [])
            self.kometa_base = config.get("kometa_base", "")
            self.temp_dir = config.get("temp_dir", "")
            self.save_to_kometa = config.get("save_to_kometa", False)
            self.stage_assets = config.get("stage_assets", True)
            self.bulk_txt = config.get("bulk_txt", "bulk_import.txt")
            self.track_artwork_ids = config.get("track_artwork_ids", True)
            self.auto_manage_bulk_files = config.get("auto_manage_bulk_files", True)
            self.reset_overlay = config.get("reset_overlay", False)
            self.schedules = config.get("schedules", [])
            self.auth_enabled = config.get("auth_enabled", False)
            self.auth_username = config.get("auth_username", "")
            self.auth_password_hash = config.get("auth_password_hash", "")
            self.ip_binding = config.get("ip_binding", DEFAULT_IP_BINDING)

        except Exception as e:
            raise ConfigLoadError(f"Failed to load config from {self.path}: {str(e)}") from e

    def create(self) -> None:
        """Create a new configuration file with default values."""
        print(f"[DEBUG Config.create] Creating config at: {self.path}")
        print(f"[DEBUG Config.create] Path is absolute: {os.path.isabs(self.path)}")
        print(f"[DEBUG Config.create] Parent directory: {os.path.dirname(self.path)}")
        print(f"[DEBUG Config.create] Parent dir exists: {os.path.isdir(os.path.dirname(self.path)) if os.path.dirname(self.path) else 'N/A (current dir)'}")

        config_json = {
            "base_url": "",
            "token": "",
            "bulk_txt": "bulk_import.txt",
            "tv_library": ["TV Shows"],
            "movie_library": ["Movies"],
            "mediux_filters": ["title_card", "background", "season_cover", "show_cover", "movie_poster",
                               "collection_poster"],
            "tpdb_filters": ["title_card", "background", "season_cover", "show_cover", "movie_poster",
                             "collection_poster"],
            "kometa_base": "",
            "temp_dir": "",
            "save_to_kometa": False,
            "stage_assets": False,
            "track_artwork_ids": True,
            "auto_manage_bulk_files": True,
            "reset_overlay": False,
            "schedules": []
        }

        # Create the config.json file if it doesn't exist
        if not os.path.isfile(self.path):
            print(f"[DEBUG Config.create] File does not exist, attempting to create")
            try:
                # Ensure parent directory exists
                parent_dir = os.path.dirname(self.path)
                if parent_dir and not os.path.isdir(parent_dir):
                    print(f"[DEBUG Config.create] Creating parent directory: {parent_dir}")
                    os.makedirs(parent_dir, exist_ok=True)

                print(f"[DEBUG Config.create] Opening file for writing: {self.path}")
                with open(self.path, "w", encoding="utf-8") as config_file:
                    json.dump(config_json, config_file, indent=4)
                print(f"[DEBUG Config.create] File written successfully")
                debug_me(f"Config file '{self.path}' created with default settings.", "Config/create")
            except Exception as e:
                print(f"[ERROR Config.create] Exception: {type(e).__name__}: {str(e)}")
                import traceback
                traceback.print_exc()
                raise ConfigCreationError(f"Failed to create config file at {self.path}: {str(e)}") from e
        else:
            print(f"[DEBUG Config.create] File already exists, skipping creation")

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
            "auto_manage_bulk_files": self.auto_manage_bulk_files,
            "reset_overlay": self.reset_overlay,
            "schedules": self.schedules,
            "auth_enabled": self.auth_enabled,
            "auth_username": self.auth_username,
            "auth_password_hash": self.auth_password_hash,
            "ip_binding": self.ip_binding
        }

        try:
            with open(self.path, "w", encoding="utf-8") as config_file:
                json.dump(config_json, config_file, indent=4)
        except Exception as e:
            raise ConfigSaveError(f"Failed to save config to {self.path}: {str(e)}") from e
