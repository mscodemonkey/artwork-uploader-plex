"""
Command line or bulk file arguments, just a container to pass them around easily
"""

from dataclasses import dataclass, field
from typing import List, Optional
from core.enums import FilterType


@dataclass
class Options:
    """
    Container for scraping and upload options that can be specified via CLI,
    bulk files, or web UI.

    Attributes:
        add_posters: Include additional posters from ThePosterDB set
        add_sets: Include additional sets from ThePosterDB
        kometa: Save artwork to Kometa asset directory instead of uploading to Plex
        stage: Download artwork for seasons and episodes not yet in Plex (except Specials)
        temp: Use temporary directory instead of Kometa asset directory
        force: Force re-upload even if artwork hasn't changed
        filters: List of artwork types to include (e.g., ['show_cover', 'title_card'])
        exclude: List of artwork IDs to skip
        year: Override year for Plex matching
        add_to_bulk: Add successfully processed URLs to bulk file
    """

    add_posters: bool = False
    add_sets: bool = False
    kometa: bool = False
    stage: bool = False
    temp: bool = False
    force: bool = False
    filters: List[str] = field(default_factory=list)
    exclude: Optional[List[str]] = None
    year: Optional[int] = None
    add_to_bulk: bool = False

    def has_filter(self, filter_type: str) -> bool:
        """Check if a specific filter type is enabled."""
        return self.filters and filter_type in self.filters

    def has_no_filters(self) -> bool:
        """Check if no filters are set (meaning all types allowed)."""
        return not self.filters

    def clear_filters(self) -> None:
        """Remove all filters."""
        self.filters = []

    def is_excluded(self, item_id: str, season: Optional[int] = None, episode: Optional[int] = None) -> bool:
        """
        Check if an artwork ID should be excluded.

        Args:
            item_id: The artwork ID to check
            season: Optional season number for TV shows
            episode: Optional episode number for TV shows

        Returns:
            True if the item should be excluded, False otherwise

        Examples:
            - exclude=['123'] excludes artwork ID '123'
            - exclude=['s01e05'] excludes season 1 episode 5
            - exclude=['s01'] excludes all of season 1
            - exclude=['s00e01', 's02'] excludes specials episode 1 and all of season 2
        """
        if self.exclude is None:
            return False

        # Check if the artwork ID itself is excluded
        if item_id in self.exclude:
            return True

        # Check season/episode exclusions for TV shows
        if season is not None:
            # Format: s01e05 or s1e5 (case insensitive)
            if episode is not None:
                episode_patterns = [
                    f"s{season:02d}e{episode:02d}",  # s01e05
                    f"s{season}e{episode}",          # s1e5
                ]
                for pattern in episode_patterns:
                    if any(pattern.lower() == excl.lower() for excl in self.exclude):
                        return True

            # Format: s01 or s1 (whole season exclusion)
            season_patterns = [
                f"s{season:02d}",  # s01
                f"s{season}",      # s1
            ]
            for pattern in season_patterns:
                if any(pattern.lower() == excl.lower() for excl in self.exclude):
                    return True

        return False

    def __post_init__(self) -> None:
        """Validate options after initialization."""
        # Validate filters
        if self.filters:
            valid_filters = [f.value for f in FilterType]
            invalid = [f for f in self.filters if f not in valid_filters]
            if invalid:
                raise ValueError(
                    f"Invalid filter types: {invalid}. "
                    f"Valid types: {valid_filters}"
                )

        # Validate year
        if self.year is not None:
            if not isinstance(self.year, int):
                raise TypeError(f"Year must be an integer, got {type(self.year).__name__}")
            if not (1900 <= self.year <= 2100):
                raise ValueError(
                    f"Year must be between 1900-2100, got {self.year}"
                )

        # Validate exclude IDs
        if self.exclude is not None:
            if not isinstance(self.exclude, list):
                raise TypeError("exclude must be a list of strings")
            if not all(isinstance(id, str) for id in self.exclude):
                raise ValueError("All exclude IDs must be strings")