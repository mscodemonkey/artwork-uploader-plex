import re, time, unicodedata
from typing import List, Optional, Tuple, Literal, Dict
from core.enums import MediaType
from core.constants import PLEX_LIBRARY_INDEX_TIMEOUT

from utils.notifications import debug_me
from utils.utils import elapsed_time


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
        self.movie_libraries: List = []
        self.tv_libraries: List = []
        self.last_refresh: float = time.time()
        self.index: dict = {}
        self._initialize_index(movie_libraries, tv_libraries)

    def _initialize_index(self, movie_libraries:List, tv_libraries: List) -> None:
        if not movie_libraries and not tv_libraries:
            return
        
        now = time.time()
        index_timed_out = (now - self.last_refresh) > PLEX_LIBRARY_INDEX_TIMEOUT
        changed_libraries = set([lib.title for lib in self.movie_libraries]) != set([lib.title for lib in movie_libraries]) or set([lib.title for lib in self.tv_libraries]) != set([lib.title for lib in tv_libraries])

        if not self.index or changed_libraries or index_timed_out:
            self.index = {}
            debug_me(f"Initializing Plex library index")
            start_time = time.time()
            for library in movie_libraries + tv_libraries:
                self._add_library(self.index, library)

            movies = sum(len(v) for v in self.index.values() if any(movie["type"] == MediaType.MOVIE.value for movie in v))
            shows = sum(len(v) for v in self.index.values() if any(show["type"] == MediaType.TV_SHOW.value for show in v))
            debug_me(f"Indexed {movies} movie and "
                        f"{shows} TV index entries "
                        f"across {len(self.movie_libraries) + len(self.tv_libraries)} libraries "
                        f"in {time.time() - start_time:.1f}s")
            self.last_refresh = time.time()
            self.movie_libraries = movie_libraries
            self.tv_libraries = tv_libraries
        else:
            debug_me(f"Index is still fresh ({elapsed_time(now - self.last_refresh)}), skipping re-indexing")
            

    def _add_library(self, index: dict, library) -> None:
        n = 0
        for item in library.all():
            n += 1
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
            entry = {
                "title": item.title,
                "year": item.year,
                "tmdb_id": tmdb_id,
                "library": library.title,
                "type": MediaType.TV_SHOW.value if library.type == "show" else MediaType.MOVIE.value
            }
            for key in self._title_keys(item):
                index.setdefault(key, []).append(entry)
        debug_me(f"Added {n} {MediaType.TV_SHOW.value if library.type == "show" else MediaType.MOVIE.value} items from library {library.title} to index")

    def _title_keys(self, item) -> set:
        """All the normalized keys an item should be findable under."""
        keys = {normalize_title(item.title)}
        slug_without_year = item.slug.split(f"-{item.year}")[0].strip()
        keys.add(normalize_title(slug_without_year))
        if item.originalTitle:
            keys.add(normalize_title(item.originalTitle))
        
        # Also index without a trailing parenthetical, so "The Office (US)" is findable as "The Office"
        stripped = re.sub(r"\s*\([^)]*\)\s*$", "", item.title)
        if stripped and stripped != item.title:
            keys.add(normalize_title(stripped))
        keys.discard("")
        return keys

    def lookup(self, title: str, year: Optional[int] = None, kind: Optional[Literal[MediaType.TV_SHOW, MediaType.MOVIE]] = None) -> Tuple[Literal['matched', 'ambiguous', 'not_found'], Optional[Dict]]:
        """
        Look up a title/year in the index.

        Returns a tuple of:
        - status (str): "matched", "ambiguous" or "not_found"
        - tmdb_id (int | None): the TMDb ID when status is "matched"
        """
        _kind = [kind] if kind is not None else [MediaType.TV_SHOW, MediaType.MOVIE]
        lookup_string = normalize_title(title)
        candidates = [c for c in self.index.get(lookup_string, []) if c["type"] in _kind]
        if candidates and year is not None:
            for candidate_year in (year, int(year) - 1, int(year) + 1):
                matched = [c for c in candidates if c["year"] == candidate_year]
                if matched:
                    break
        else:
            matched = candidates
        tmdb_ids = {c.get("tmdb_id", None) for c in matched if c.get("tmdb_id", None) is not None}

        # If multiple items have been found by title/year but they all have the same TMDb ID (same item across multiple libraries),
        # or if a single item has been matched by title/year, even if it has no TMDb ID, then we have a match
        if len(tmdb_ids) == 1 or len(matched) == 1:
            match = next(item for item in matched)
            return "matched", match

        # If multiple items have been returned with differing TMDb IDs then we have an ambiguous match
        if len(tmdb_ids) > 1:
            return "ambiguous", None
        
        return "not_found", None
