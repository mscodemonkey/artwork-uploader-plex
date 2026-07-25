import re
import time
import unicodedata
from typing import List, Optional, Tuple

from utils.notifications import debug_me


def normalize_title(title: str) -> str:
    """Lowercase, strip accents and punctuation so titles compare equal regardless of styling,
       e.g. 'Mission: Impossible' vs 'Mission - Impossible', 'Léon' vs 'Leon', 'Mad Max 2' vs 'Mad Max 2!'"""
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    title = title.casefold().replace("&", " and ")
    title = re.sub(r"[^\w\s]", " ", title)
    return re.sub(r"\s+", " ", title).strip()


class PlexLibraryIndex:
    """
    In-memory index of the configured Plex libraries, so scraped artwork can be matched to
    the library by title and year without a web request per asset.

    Built once per processing run from a single request per library (library.all() includes
    guids, titles and years in one response - see the plexapi getGuid docs, which recommend
    exactly this kind of lookup dictionary for performance).
    """

    def __init__(self, movie_libraries: List, tv_libraries: List) -> None:
        self.movie_index: dict = {}
        self.tv_index: dict = {}
        start_time = time.time()
        for library in movie_libraries:
            self._add_library(self.movie_index, library)
        for library in tv_libraries:
            self._add_library(self.tv_index, library)
        debug_me(f"Indexed {sum(len(v) for v in self.movie_index.values())} movie and "
                 f"{sum(len(v) for v in self.tv_index.values())} TV index entries "
                 f"in {time.time() - start_time:.1f}s", "PlexLibraryIndex/__init__")

    def _add_library(self, index: dict, library) -> None:
        for item in library.all():
            # Index values come from the listing response only - without this, reading an attribute
            # the item doesn't have (e.g. originalTitle on most items) makes plexapi reload the
            # item, which would be one extra request per library item
            item._autoReload = False
            tmdb_id: Optional[int] = None
            for guid in item.guids:
                if "tmdb://" in guid.id:
                    try:
                        tmdb_id = int(guid.id.split("tmdb://", 1)[-1])
                    except ValueError:
                        pass
                    break
            entry = (item.year, tmdb_id)
            for key in self._title_keys(item.title, getattr(item, "originalTitle", None)):
                index.setdefault(key, []).append(entry)

    def _title_keys(self, title: str, original_title: Optional[str]) -> set:
        """All the normalized keys an item should be findable under."""
        keys = {normalize_title(title)}
        if original_title:
            keys.add(normalize_title(original_title))
        # Also index without a trailing parenthetical, so "The Office (US)" is findable as "The Office"
        stripped = re.sub(r"\s*\([^)]*\)\s*$", "", title)
        if stripped and stripped != title:
            keys.add(normalize_title(stripped))
        keys.discard("")
        return keys

    def lookup(self, kind: str, title: str, year: Optional[int]) -> Tuple[str, Optional[int]]:
        """
        Look up a title/year in the index.

        Returns a tuple of:
        - status (str): "matched", "ambiguous" or "not_found"
        - tmdb_id (int | None): the TMDb ID when status is "matched"
        """
        index = self.movie_index if kind == "movie" else self.tv_index
        candidates = index.get(normalize_title(title), [])
        if candidates and year is not None:
            # Same retry pattern as PlexConnector.movie_or_show: exact year, then -1, then +1
            for candidate_year in (year, int(year) - 1, int(year) + 1):
                matched = [c for c in candidates if c[0] == candidate_year]
                if matched:
                    break
        else:
            matched = candidates
        tmdb_ids = {tmdb_id for _, tmdb_id in matched if tmdb_id is not None}
        if len(tmdb_ids) == 1:
            return "matched", tmdb_ids.pop()
        if len(tmdb_ids) > 1:
            return "ambiguous", None
        return "not_found", None
