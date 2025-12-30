"""
Unified exception hierarchy for the Artwork Uploader application.

All custom exceptions inherit from ArtworkUploaderException for easier
exception handling and to distinguish application errors from system errors.
"""


class ArtworkUploaderException(Exception):
    """Base exception for all application errors."""
    pass


# ============================================================================
# Configuration errors
# ============================================================================

class ConfigurationError(ArtworkUploaderException):
    """Base class for configuration-related errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ConfigLoadError(ConfigurationError):
    """The config file had a problem when loading."""
    pass


class ConfigSaveError(ConfigurationError):
    """The config file could not be saved."""
    pass


class ConfigCreationError(ConfigurationError):
    """The config file could not be created."""
    pass


# ============================================================================
# Plex errors
# ============================================================================

class PlexError(ArtworkUploaderException):
    """Base class for Plex-related errors."""

    def __init__(self, message: str, gui_message: str = None) -> None:
        super().__init__(message)
        self.gui_message = gui_message if gui_message is not None else message


class PlexConnectorException(PlexError):
    """General Plex connection error."""
    pass


class LibraryNotFound(PlexError):
    """The requested library could not be found."""
    pass


# ============================================================================
# Scraper errors
# ============================================================================

class ScraperError(ArtworkUploaderException):
    """Base class for scraper-related errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ScraperException(ScraperError):
    """General scraping error."""
    pass


# ============================================================================
# Upload errors
# ============================================================================

class UploadError(ArtworkUploaderException):
    """Base class for upload-related errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class CollectionNotFound(UploadError):
    """A collection was not found for the artwork provided."""
    pass


class MovieNotFound(UploadError):
    """A movie was not found for the artwork provided."""
    pass


class ShowNotFound(UploadError):
    """A TV show was not found for the artwork provided."""
    pass


class NotProcessedByFilter(UploadError):
    """An item was not uploaded due to a filter being applied."""
    pass


class NotProcessedByExclusion(UploadError):
    """An item was not uploaded due to an exclusion being applied."""
    pass
