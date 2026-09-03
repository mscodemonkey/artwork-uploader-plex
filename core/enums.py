"""
Enumerations for type-safe constants throughout the application.
"""

from enum import Enum


class FilterType(str, Enum):
    """Valid artwork filter types."""
    TITLE_CARD = "title_card"
    BACKGROUND = "background"
    SEASON_COVER = "season_cover"
    SHOW_COVER = "show_cover"
    MOVIE_POSTER = "movie_poster"
    COLLECTION_POSTER = "collection_poster"
    SQUARE_ART = "square_art"


class MediaType(str, Enum):
    """Media types supported by the application."""
    TV_SHOW = "TV Show"
    MOVIE = "Movie"
    COLLECTION = "Collection"
    PERSON = "Person"
    CATEGORY = "Category"
    COMPANY = "Company"
    UNKNOWN = "Unknown"


class ScraperSource(str, Enum):
    """Sources from which artwork can be obtained."""
    THEPOSTERDB = "theposterdb"
    MEDIUX = "mediux"
    UPLOAD = "Upload"


class ArtworkIDPrefix(str, Enum):
    """Prefixes for artwork ID labels in Plex."""
    BACKGROUND = "BID:"
    SQUARE_ART = "SAID:"
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


class NotificationEvent(str, Enum):
    """Events that can trigger a notification, individually switchable per channel."""
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_COMPLETED_WITH_ERRORS = "run_completed_with_errors"
    RUN_FAILED_TO_START = "run_failed_to_start"
    RUN_SKIPPED = "run_skipped"
    RUN_CANCELLED = "run_cancelled"


class FileType(str, Enum):
    """File types in MediUX responses."""
    TITLE_CARD = "title_card"
    BACKDROP = "backdrop"
    BACKGROUND = "background"
    POSTER = "poster"
    SEASON_COVER = "season_cover"
    SHOW_COVER = "show_cover"
    MOVIE_POSTER = "movie_poster"
    COLLECTION_POSTER = "collection_poster"
    ALBUM_ART = "album_art"
    SQUARE_ART = "square_art"

class RunType(str, Enum):
    """Types of runs"""
    BULK = "bulk"       # a bulk import file, manual or scheduled
    SCRAPE = "scrape"   # a single URL scraped from the main tab
    UPLOAD = "upload"   # an artwork ZIP uploaded through the browser
    WEBHOOK = "webhook" # a Radarr/Sonarr import applied from the cache

class RunTrigger(str, Enum):
    """Type of trigger that triggered a run"""
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    CLI = "cli"
    RADARR = "radarr"
    SONARR = "sonarr"

class RunOutcome(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial" # completed, but one or more items errored
    STOPPED = "stopped" # cancelled by the user
    FAILED = "failed"   # an exception aborted the run
    SKIPPED = "skipped" # nothing to do (e.g. no valid entries in the file)

class WebhookSource(str, Enum):
    RADARR = "radarr"
    SONARR = "sonarr"

class IntervalUnit(str, Enum):
    DAYS = "days"
    HOURS = "hours"

class AuthType(str, Enum):
    BASIC = "basic"
    OIDC = "oidc"
