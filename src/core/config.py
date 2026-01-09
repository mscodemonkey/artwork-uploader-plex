"""
Application configuration management.
"""

import json
import os
from typing import List, Dict, Any

from core.constants import DEFAULT_CONFIG_PATH, DEFAULT_BULK_IMPORT_FILE, DEFAULT_TV_LIBRARY, DEFAULT_MOVIE_LIBRARY, DEFAULT_IP_BINDING
from core.exceptions import ConfigLoadError, ConfigSaveError, ConfigCreationError
from logging_config import get_logger

logger = get_logger(__name__)


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
        stage_specials: Whether to save specials (season 0) artwork to Kometa even when the season doesn't exist in Plex
        stage_collections: Whether to save collection artwork to Kometa even when the collection doesn't exist in Plex
        track_artwork_ids: Whether to track artwork IDs using Plex labels
        auto_manage_bulk_files: Whether to auto-organize bulk files
        reset_overlay: Whether to reset Kometa overlay labels on upload
        schedules: List of scheduled bulk import jobs
        auth_enabled: Whether authentication is enabled for the web server
        auth_username: Username for web server authentication
        auth_password_hash: Hashed password for web server authentication
        ip_binding: IP binding mode - "auto" (default), "ipv4", or "ipv6"
        debug: Enable debug logging
        kometa_library_paths: Dictionary mapping Plex library names to Kometa directory names
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
        self.stage_specials: bool = False
        self.stage_collections: bool = False
        self.track_artwork_ids: bool = True
        self.auto_manage_bulk_files: bool = True
        self.reset_overlay: bool = False
        self.schedules: List[Dict[str, Any]] = []
        self.auth_enabled: bool = False
        self.auth_username: str = ""
        self.auth_password_hash: str = ""
        self.ip_binding: str = DEFAULT_IP_BINDING
        self.debug: bool = False
        self.kometa_library_paths: Dict[str, str] = {}

    def load(self) -> None:
        """Load the configuration from the JSON file."""
        logger.debug(f"Config path: {self.path}")
        logger.debug(f"File exists: {os.path.isfile(self.path)}")

        # If a config file doesn't exist, create one with default values
        if not os.path.isfile(self.path):
            logger.debug("Config file does not exist, calling create()")
            self.create()
            logger.debug(
                f"After create(), file exists: {os.path.isfile(self.path)}")

        # Load the configuration from the config.json file
        logger.debug(
            f"Attempting to open config file for reading: {self.path}")
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
            self.stage_specials = config.get("stage_specials", False)
            self.stage_collections = config.get("stage_collections", False)
            self.bulk_txt = config.get("bulk_txt", "bulk_import.txt")
            self.track_artwork_ids = config.get("track_artwork_ids", True)
            self.auto_manage_bulk_files = config.get(
                "auto_manage_bulk_files", True)
            self.reset_overlay = config.get("reset_overlay", False)
            self.schedules = config.get("schedules", [])
            self.auth_enabled = config.get("auth_enabled", False)
            self.auth_username = config.get("auth_username", "")
            self.auth_password_hash = config.get("auth_password_hash", "")
            self.ip_binding = config.get("ip_binding", DEFAULT_IP_BINDING)
            self.debug = config.get("debug", False)
            self.kometa_library_paths = config.get("kometa_library_paths", {})

        except Exception as e:
            raise ConfigLoadError(
                f"Failed to load config from {self.path}: {str(e)}") from e

    def create(self) -> None:
        """Create a new configuration file with default values."""
        logger.debug(f"Creating config at: {self.path}")
        logger.debug(f"Path is absolute: {os.path.isabs(self.path)}")
        logger.debug(f"Parent directory: {os.path.dirname(self.path)}")
        parent_exists = os.path.isdir(os.path.dirname(self.path)) if os.path.dirname(
            self.path) else 'N/A (current dir)'
        logger.debug(f"Parent dir exists: {parent_exists}")

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
            "stage_specials": False,
            "stage_collections": False,
            "track_artwork_ids": True,
            "auto_manage_bulk_files": True,
            "reset_overlay": False,
            "schedules": [],
            "debug": False,
            "kometa_library_paths": {}
        }

        # Create the config.json file if it doesn't exist
        if not os.path.isfile(self.path):
            logger.debug("File does not exist, attempting to create")
            try:
                # Ensure parent directory exists
                parent_dir = os.path.dirname(self.path)
                if parent_dir and not os.path.isdir(parent_dir):
                    logger.debug(f"Creating parent directory: {parent_dir}")
                    os.makedirs(parent_dir, exist_ok=True)

                logger.debug(f"Opening file for writing: {self.path}")
                with open(self.path, "w", encoding="utf-8") as config_file:
                    json.dump(config_json, config_file, indent=4)
                logger.debug("File written successfully")
                logger.info(
                    f"Config file '{self.path}' created with default settings.")
            except Exception as e:
                logger.error(
                    f"Failed to create config file at {self.path}", exc_info=True)
                raise ConfigCreationError(
                    f"Failed to create config file at {self.path}: {str(e)}") from e
        else:
            logger.debug("File already exists, skipping creation")

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
            "stage_specials": self.stage_specials,
            "stage_collections": self.stage_collections,
            "bulk_txt": self.bulk_txt,
            "track_artwork_ids": self.track_artwork_ids,
            "auto_manage_bulk_files": self.auto_manage_bulk_files,
            "reset_overlay": self.reset_overlay,
            "schedules": self.schedules,
            "auth_enabled": self.auth_enabled,
            "auth_username": self.auth_username,
            "auth_password_hash": self.auth_password_hash,
            "ip_binding": self.ip_binding,
            "debug": self.debug,
            "kometa_library_paths": self.kometa_library_paths
        }

        try:
            with open(self.path, "w", encoding="utf-8") as config_file:
                json.dump(config_json, config_file, indent=4)
        except Exception as e:
            raise ConfigSaveError(
                f"Failed to save config to {self.path}: {str(e)}") from e

    def resolve_library_directory(self, library_name: str) -> str:
        """
        Resolve the directory name for a given Plex library.

        If the library is mapped in kometa_library_paths, return the mapped name.
        Otherwise, return the library name as-is (backward compatible).

        Args:
            library_name: The name of the Plex library

        Returns:
            The directory name to use in the Kometa asset structure
        """
        return self.kometa_library_paths.get(library_name, library_name)
