"""
Version information for Artwork Uploader for Plex.

This module provides version metadata for the application.
Import version information from here rather than hardcoding it elsewhere.
"""

__version__ = "0.6.5"
__version_info__ = (0, 6, 5, "patch")
__author__ = "mscodemonkey"
__license__ = "MIT"
__url__ = "https://github.com/mscodemonkey/artwork-uploader-plex"
__description__ = "Automated artwork uploader for Plex from ThePosterDB and MediUX"


def get_version_string() -> str:
    """
    Get formatted version string for display.

    Returns:
        Formatted version string (e.g., "Artwork Uploader for Plex v0.3.7-beta")
    """
    return f"Artwork Uploader for Plex v{__version__}"


def get_version_tuple() -> tuple:
    """
    Get version as a tuple for comparison.

    Returns:
        Version tuple (major, minor, patch, pre-release)
    """
    return __version_info__
