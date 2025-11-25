"""
Type definitions for artwork data structures.

Defines TypedDict classes for the various artwork dictionaries passed
throughout the application. This provides type safety and IDE support
for artwork data.
"""

from typing import TypedDict, Optional, Union, Literal


class MovieArtwork(TypedDict):
    """
    Type definition for movie artwork data.

    Used when scraping or uploading movie posters.
    """
    title: str
    url: str
    year: Optional[int]
    source: str  # Should be ScraperSource value
    id: str
    type: Optional[str] # Added by me
    author: Optional[str] # Added by me
    tmdb_id: Optional[int]  # Added by me


class TVArtwork(TypedDict):
    """
    Type definition for TV show artwork data.

    Used when scraping or uploading TV show artwork including:
    - Show covers
    - Season covers
    - Title cards (episode artwork)
    - Backgrounds/backdrops
    """
    title: str
    url: str
    season: Union[int, str]  # int for season number, or "Cover"/"Backdrop"
    episode: Optional[Union[int, str]]  # int for episode number, "Cover", or None
    year: Optional[int]
    source: str  # Should be ScraperSource value
    id: str
    type: Optional[str]  # Should be FilterType value (optional, used by MediUX)
    author: Optional[str]  # Added by me
    tmdb_id: Optional[int]  # Added by me


class CollectionArtwork(TypedDict):
    """
    Type definition for collection artwork data.

    Used when scraping or uploading movie collection posters.
    """
    title: str
    url: str
    source: str  # Should be ScraperSource value
    id: str
    type: Optional[str] # Added by me
    year: Optional[int] # Added by me
    author: Optional[str]  # Added by me


class UploadedFileArtwork(TypedDict):
    """
    Type definition for uploaded file artwork.

    Used when processing locally uploaded image files.
    """
    title: str
    path: str
    checksum: str
    source: Literal["Upload"]
    id: Literal["Upload"]
    season: Optional[Union[int, str]]
    episode: Optional[Union[int, str]]
    media: Optional[str]  # "Movie", "TV Show", "Collection"
    year: Optional[int]


# Type aliases for common artwork lists
MovieArtworkList = list[MovieArtwork]
TVArtworkList = list[TVArtwork]
CollectionArtworkList = list[CollectionArtwork]


# Union type for any artwork
AnyArtwork = Union[MovieArtwork, TVArtwork, CollectionArtwork, UploadedFileArtwork]
