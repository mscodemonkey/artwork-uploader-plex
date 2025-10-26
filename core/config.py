"""
Application configuration management.
"""

import json
import os
from typing import List, Dict, Any

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
        track_artwork_ids: Whether to track artwork IDs using Plex labels
        auto_manage_bulk_files: Whether to auto-organize bulk files
        reset_overlay: Whether to reset Kometa overlay labels on upload
        schedules: List of scheduled bulk import jobs
    """

    def __init__(self, config_path: str = "config.json") -> None:
        self.path: str = config_path
        self.base_url: str = ""
        self.token: str = ""
        self.bulk_txt: str = "bulk_import.txt"
        self.tv_library: List[str] = ["TV Shows"]
        self.movie_library: List[str] = ["Movies"]
        self.mediux_filters: List[str] = ["title_card", "background", "season_cover", "show_cover", "movie_poster", "collection_poster"]
        self.tpdb_filters: List[str] = ["title_card", "background", "season_cover", "show_cover", "movie_poster", "collection_poster"]
        self.kometa_base: str = "C:\\Temp\\assets"
        self.temp_dir: str = "C:\\Temp\\assets\\temp"
        self.save_to_kometa: bool = False
        self.track_artwork_ids: bool = True
        self.auto_manage_bulk_files: bool = True
        self.reset_overlay: bool = False
        self.schedules: List[Dict[str, Any]] = []
        self.auth_enabled: bool = False
        self.auth_username: str = ""
        self.auth_password_hash: str = ""


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
            self.kometa_base = config.get("kometa_base", "")
            self.temp_dir = config.get("temp_dir", "")
            self.save_to_kometa = config.get("save_to_kometa", False)
            self.bulk_txt = config.get("bulk_txt", "bulk_import.txt")
            self.track_artwork_ids = config.get("track_artwork_ids", True)
            self.auto_manage_bulk_files = config.get("auto_manage_bulk_files", True)
            self.reset_overlay = config.get("reset_overlay", False)
            self.schedules = config.get("schedules", [])
            self.auth_enabled = config.get("auth_enabled", False)
            self.auth_username = config.get("auth_username", "")
            self.auth_password_hash = config.get("auth_password_hash", "")

        except Exception as e:
            raise ConfigLoadError from e

    def create(self) -> None:
        """Create a new configuration file with default values."""
        config_json = {
            "base_url": "",
            "token": "",
            "bulk_txt": "bulk_import.txt",
            "tv_library": ["TV Shows"],
            "movie_library": ["Movies"],
            "mediux_filters": ["title_card", "background", "season_cover", "show_cover", "movie_poster", "collection_poster"],
            "tpdb_filters": ["title_card", "background", "season_cover", "show_cover", "movie_poster", "collection_poster"],
            "kometa_base": "C:\\Temp\\assets",
            "temp_dir": "C:\\Temp\\assets\\temp",
            "save_to_kometa": False,
            "track_artwork_ids": True,
            "auto_manage_bulk_files": True,
            "reset_overlay": False,
            "schedules": []
        }

        # Create the config.json file if it doesn't exist
        if not os.path.isfile(self.path):
            try:
                with open(self.path, "w", encoding="utf-8") as config_file:
                    json.dump(config_json, config_file, indent=4)
                debug_me(f"Config file '{self.path}' created with default settings.", "Config/create")
            except Exception as e:
                raise ConfigCreationError from e

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
            "bulk_txt": self.bulk_txt,
            "track_artwork_ids": self.track_artwork_ids,
            "auto_manage_bulk_files": self.auto_manage_bulk_files,
            "reset_overlay": self.reset_overlay,
            "schedules": self.schedules,
            "auth_enabled": self.auth_enabled,
            "auth_username": self.auth_username,
            "auth_password_hash": self.auth_password_hash
        }

        try:
            with open(self.path, "w", encoding="utf-8") as config_file:
                json.dump(config_json, config_file, indent=4)
        except Exception as e:
            raise ConfigSaveError from e
