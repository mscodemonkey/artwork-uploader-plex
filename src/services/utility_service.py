"""
Service for utility functions.

Extracted from artwork_uploader.py to reduce file size and improve
maintainability.
"""

import os
import sys
from typing import Any, Tuple


class UtilityService:
    """Provides utility functions for the application."""

    @staticmethod
    def get_exe_dir() -> str:
        """
        Get the directory of the executable or script file.

        Returns:
            Directory path of the executable (if frozen) or script file
        """
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)  # Path to executable
        else:
            # When called from services/ subdir, go up one level to project root
            return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @staticmethod
    def sort_key(item: dict) -> Tuple[str, float, float, str]:
        """
        Generate a sort key for artwork items.

        Sorts by: media type, season, episode, source

        Args:
            item: Dictionary with 'media', 'season', 'episode', 'source' keys

        Returns:
            Tuple for sorting (media, season_value, episode_value, source_value)
        """

        def parse_season(season: Any) -> float:
            # If the season is missing, None, or non-numeric, treat it as the highest possible value
            if season is None or not isinstance(season, (int, str)) or (
                    isinstance(season, str) and not season.isdigit()):
                return float('inf')
            return int(season)

        def parse_episode(episode: Any) -> float:
            # Handle missing or non-numeric episodes
            return int(episode) if isinstance(episode, int) else float('inf')

        def parse_source(source: Any) -> str:
            # Treat missing source or invalid entries as empty string to ensure they are last
            return source if source else ''

        # Now safely get the values, even if they are missing
        season_value = parse_season(item.get('season'))  # Using .get() to avoid KeyError
        episode_value = parse_episode(item.get('episode'))  # Same for episode
        source_value = parse_source(item.get('source'))  # Same for source

        return item['media'], season_value, episode_value, source_value
