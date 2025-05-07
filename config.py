import json
import os
from typing import TextIO

from config_exceptions import ConfigLoadError, ConfigSaveError, ConfigCreationError
from notifications import debug_me

class Config:

    def __init__(self, config_path="config.json"):
        self.path = config_path
        self.base_url = ""
        self.token = ""
        self.bulk_txt = "bulk_import.txt"
        self.tv_library = ["TV Shows"]
        self.movie_library = ["Movies"]
        self.mediux_filters = ["title_card", "background", "season_cover", "show_cover","movie_poster","collection_poster"]
        self.tpdb_filters = ["title_card", "background", "season_cover", "show_cover","movie_poster","collection_poster"]
        self.track_artwork_ids = True
        self.auto_manage_bulk_files = True
        self.reset_overlay = False
        self.schedules = []


    def load(self):
        """ Load the configuration from the JSON file """

        # If a config file doesn't exist, create one with default values
        if not os.path.isfile(self.path):
            self.create()

        # Load the configuration from the config.json file
        try:
            with open(self.path, "r") as config_file:
                config = json.load(config_file)

            self.base_url = config.get("base_url", "")
            self.token = config.get("token", "")
            self.tv_library = config.get("tv_library", [])
            self.movie_library = config.get("movie_library", [])
            self.mediux_filters = config.get("mediux_filters", [])
            self.tpdb_filters = config.get("tpdb_filters", [])
            self.bulk_txt = config.get("bulk_txt", "bulk_import.txt")
            self.track_artwork_ids = config.get("track_artwork_ids", True)
            self.auto_manage_bulk_files = config.get("auto_manage_bulk_files", True)
            self.reset_overlay = config.get("reset_overlay", False)
            self.schedules = config.get("schedules",[])

        except Exception as e:
            raise ConfigLoadError

    def create(self):
        config_json = {
            "base_url": "",
            "token": "",
            "bulk_txt": "bulk_import.txt",
            "tv_library": ["TV Shows"],
            "movie_library": ["Movies"],
            "mediux_filters": ["title_card", "background", "season_cover", "show_cover","movie_poster","collection_poster"],
            "tpdb_filters":["title_card", "background", "season_cover", "show_cover", "movie_poster", "collection_poster"],
            "track_artwork_ids": True,
            "auto_manage_bulk_files": True,
            "reset_overlay": False,
            "schedules": []
        }

        # Create the config.json file if it doesn't exist
        if not os.path.isfile(self.path):
            try:
                with open(self.path, "w", encoding="utf-8") as config_file:  # type: TextIO
                    json.dump(config_json, config_file, indent=4)
                debug_me(f"Config file '{self.path}' created with default settings.")
            except Exception as e:
                raise ConfigCreationError

    def save(self):
        """Save the configuration from the UI fields to the file and update the in-memory config."""

        for schedule in self.schedules:
            schedule.pop("jobReference", None)

        config_json = {
            "base_url": self.base_url,
            "token": self.token,
            "tv_library": self.tv_library,
            "movie_library": self.movie_library,
            "mediux_filters": self.mediux_filters,
            "tpdb_filters": self.tpdb_filters,
            "bulk_txt": self.bulk_txt,
            "track_artwork_ids": self.track_artwork_ids,
            "auto_manage_bulk_files": self.auto_manage_bulk_files,
            "reset_overlay": self.reset_overlay,
            "schedules": self.schedules
        }

        try:
            with open(self.path, "w", encoding="utf-8") as config_file:
                json.dump(config_json, config_file, indent=4)
        except Exception as e:
            raise ConfigSaveError

