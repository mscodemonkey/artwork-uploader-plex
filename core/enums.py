"""
Enumerations for type-safe constants throughout the application.
"""

from enum import Enum, auto


class FilterType(str, Enum):
    """Valid artwork filter types."""
    TITLE_CARD = "title_card"
    BACKGROUND = "background"
    SEASON_COVER = "season_cover"
    SHOW_COVER = "show_cover"
    MOVIE_POSTER = "movie_poster"
    COLLECTION_POSTER = "collection_poster"


class MediaType(str, Enum):
    """Media types supported by the application."""
    TV_SHOW = "TV Show"
    MOVIE = "Movie"
    COLLECTION = "Collection"
    UNKNOWN = "Unknown"


class ScraperSource(str, Enum):
    """Sources from which artwork can be obtained."""
    THEPOSTERDB = "theposterdb"
    MEDIUX = "mediux"
    UPLOAD = "Upload"


class ArtworkIDPrefix(str, Enum):
    """Prefixes for artwork ID labels in Plex."""
    BACKGROUND = "BID:"
    SHOW_COVER = "CID:"
    POSTER = "PID:"
    SEASON = "SID:"
    EPISODE = "EID:"


class InstanceMode(str, Enum):
    """Operating modes for the application."""
    CLI = "cli"
    WEB = "web"


class SeasonValue(str, Enum):
    """Special season identifier values."""
    COVER = "Cover"
    BACKDROP = "Backdrop"
    SPECIALS = "Specials"


class StatusColor(str, Enum):
    """Status message color types (Bootstrap colors)."""
    PRIMARY = "primary"
    SECONDARY = "secondary"
    SUCCESS = "success"
    DANGER = "danger"
    WARNING = "warning"
    INFO = "info"
    LIGHT = "light"
    DARK = "dark"


class FileType(str, Enum):
    """File types in MediUX responses."""
    TITLE_CARD = "title_card"
    BACKDROP = "backdrop"
    POSTER = "poster"
