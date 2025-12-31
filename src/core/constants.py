"""
Application-wide constants.
"""

import os

from core.__version__ import __version__, __url__

# Application metadata
APP_NAME = "Media Artwork Uploader for Plex/Kometa"
CURRENT_VERSION = f"v{__version__}"
GITHUB_REPO = __url__.replace("https://github.com/", "")

# Python version requirements
MIN_PYTHON_MAJOR = 3
MIN_PYTHON_MINOR = 10

# Server configuration
DEFAULT_WEB_PORT = 4567
DEFAULT_IP_BINDING = "auto"  # Options: "auto", "ipv4", "ipv6"

# Detect Docker environment
RUNNING_IN_DOCKER = os.getenv("RUNNING_IN_DOCKER") == "1"

# File paths - environment-aware defaults
# Docker: absolute paths for volume mounts
# Non-Docker: relative paths in execution directory
DEFAULT_CONFIG_PATH = "/config/config.json" if RUNNING_IN_DOCKER else "config.json"
DEFAULT_BULK_IMPORTS_DIR = "/bulk_imports" if RUNNING_IN_DOCKER else "bulk_imports"
DEFAULT_BULK_IMPORT_FILE = "bulk_import.txt"
DEFAULT_LOGS_DIR = "/logs" if RUNNING_IN_DOCKER else "logs"

# Plex library defaults
DEFAULT_TV_LIBRARY = ["TV Shows"]
DEFAULT_MOVIE_LIBRARY = ["Movies"]

# Filter types - valid artwork types that can be filtered
FILTER_TITLE_CARD = "title_card"
FILTER_BACKGROUND = "background"
FILTER_SEASON_COVER = "season_cover"
FILTER_SHOW_COVER = "show_cover"
FILTER_MOVIE_POSTER = "movie_poster"
FILTER_COLLECTION_POSTER = "collection_poster"

ALL_FILTERS = [
    FILTER_TITLE_CARD,
    FILTER_BACKGROUND,
    FILTER_SEASON_COVER,
    FILTER_SHOW_COVER,
    FILTER_MOVIE_POSTER,
    FILTER_COLLECTION_POSTER,
]

# Artwork ID prefixes (for Plex labels)
ARTWORK_ID_BACKGROUND = "BID:"
ARTWORK_ID_SHOW_COVER = "CID:"
ARTWORK_ID_POSTER = "PID:"
ARTWORK_ID_SEASON = "SID:"
ARTWORK_ID_EPISODE = "EID:"

# Media types
MEDIA_TYPE_TV_SHOW = "TV Show"
MEDIA_TYPE_MOVIE = "Movie"
MEDIA_TYPE_COLLECTION = "Collection"

# Scraper sources
SOURCE_THEPOSTERDB = "theposterdb"
SOURCE_MEDIUX = "mediux"
SOURCE_UPLOAD = "Upload"

# ThePosterDB configuration
TPDB_BASE_URL = "https://theposterdb.com"
TPDB_API_ASSETS_URL = "https://theposterdb.com/api/assets"
TPDB_RATE_LIMIT_DELAY = 6  # seconds between requests
TPDB_USER_UPLOADS_PER_PAGE = 24
TPBD_USER_BASE_PATH = "/user/"
TPBD_SET_BASE_PATH = "/set/"
# MediUX configuration
MEDIUX_BASE_URL = "https://mediux.pro"
MEDIUX_API_BASE_URL = "https://api.mediux.pro/assets/"
MEDIUX_QUALITY_SUFFIX = "&w=3840&q=80"

# Season/Episode special values
SEASON_COVER = "Cover"
SEASON_BACKDROP = "Backdrop"
SEASON_SPECIALS = "Specials"
SEASON_SPECIALS_NUMBER = 0
EPISODE_COVER = "Cover"

# Kometa integration
KOMETA_OVERLAY_LABEL = "Overlay"

# Update check interval (seconds)
UPDATE_CHECK_INTERVAL = 1800  # 30 minutes

# Scheduler check interval (seconds)
SCHEDULER_CHECK_INTERVAL = 60  # 1 minute

# File upload
UPLOAD_CHUNK_SIZE = 8192  # bytes

# Web UI colors (Bootstrap)
BOOTSTRAP_COLORS = {
    'primary': {'bg': '#0d6efd', 'fg': '#ffffff', 'ansi': '\033[0m'},
    'secondary': {'bg': '#6c757d', 'fg': '#ffffff', 'ansi': '\033[36m'},
    'success': {'bg': '#198754', 'fg': '#ffffff', 'ansi': '\033[32m', 'icon': 'check-circle'},
    'danger': {'bg': '#dc3545', 'fg': '#ffffff', 'ansi': '\033[31m', 'icon': 'exclamation-triangle'},
    'warning': {'bg': '#ffc107', 'fg': '#212529', 'ansi': '\033[35m', 'icon': 'exclamation-circle-fill'},
    'info': {'bg': '#0dcaf0', 'fg': '#212529', 'ansi': '\033[34m', 'icon': 'info-circle'},
    'light': {'bg': '#f8f9fa', 'fg': '#212529', 'ansi': '\033[33m'},
    'dark': {'bg': '#212529', 'fg': '#ffffff', 'ansi': '\033[30m'},
}

# ANSI color codes
ANSI_RESET = '\033[0m'
ANSI_BOLD = '\033[1m'

# Instance modes
MODE_CLI = "cli"
MODE_WEB = "web"

# Comment prefixes for bulk files
COMMENT_PREFIXES = ('#', '//')

# File type patterns
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png')
VALID_FILENAME_PATTERN = r'^[^/]+(?:\.jpg|\.jpeg|\.png)$'

# Status messages
STATUS_COLORS = {
    'primary': 'primary',
    'success': 'success',
    'danger': 'danger',
    'warning': 'warning',
    'info': 'info',
}
