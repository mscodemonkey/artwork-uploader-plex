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
        self.last_refresh: Dict[str, float] = {}
        self.index: Dict[str, Dict[str, List[Dict]]] = {}
        self.library_snapshots: Dict[str, Tuple[int, Optional[object], Optional[str]]] = {}
        self._initialize_index(movie_libraries, tv_libraries)

    def _get_library_snapshot(self, library) -> Tuple[int, Optional[object], Optional[str]]:
        library.reload()
        total_size = library.totalSize
        latest_item = library.search(sort='addedAt:desc', limit=1)
        latest_added = latest_item[0].addedAt if latest_item else None
        latest_key = latest_item[0].ratingKey if latest_item else None
        return (total_size, latest_added, latest_key)

    def _initialize_index(self, movie_libraries:List, tv_libraries: List) -> None:
        if not movie_libraries and not tv_libraries:
            return
        
        current_libraries = self.movie_libraries + self.tv_libraries
        new_libraries = movie_libraries + tv_libraries

        new_titles = {lib.title for lib in new_libraries}
        removed_libraries = [lib for lib in current_libraries if lib.title not in new_titles]

        for library in removed_libraries:
            self._remove_library(library)
        
        start_time = time.time()
        any_updates = False

        for library in new_libraries:
            indexed = self._add_library(library)
            any_updates = any_updates or indexed

        self.movie_libraries = movie_libraries
        self.tv_libraries = tv_libraries

        movies = 0
        shows = 0

        for lib_dict in self.index.values():
            for entries in lib_dict.values():
                for entry in entries:
                    if entry["type"] == MediaType.MOVIE.value:
                        movies += 1
                    elif entry["type"] == MediaType.TV_SHOW.value:
                        shows += 1

        now = time.time()
        index_time = elapsed_time(now - start_time, precise=True)

        if any_updates:
            debug_me(
                f"Index update complete in {index_time}: there are {movies} movie and {shows} "
                f"TV show entries across {len(new_libraries)} libraries"
            )
        else:
            debug_me(f"No libraries required reindexing")
            
    def _remove_library(self, library) -> None:
        """ Removes the library from the index and its tracking metadata"""
        if library.title not in self.index:
            return
        
        self.index.pop(library.title, None)
        self.library_snapshots.pop(library.title, None)
        self.last_refresh.pop(library.title, None)

        debug_me(f"Removed library {library.title} from the index")

    def _add_library(self, library) -> bool:
        """ Adds a library to the index if the library is not already in the index or if the 
        content of the library has changed based on the snapshot, and it also updates the snapshot"""

        # Get current state
        last_refresh = self.last_refresh.get(library.title, 0)
        current_snapshot = self.library_snapshots.get(library.title)

        # Get new state
        now = time.time()
        new_snapshot = self._get_library_snapshot(library)

        library_changed = current_snapshot != new_snapshot
        index_expired = (now - last_refresh) > PLEX_LIBRARY_INDEX_TIMEOUT

        not_in_index = library.title not in self.index

        # If the library doesn't exist in the index or the contents of the library have changed
        # or the library index has timed out it reindexes the library from scratch
        if not_in_index or library_changed or index_expired:
            if not_in_index:
                debug_me(f"Adding library {library.title} to the Plex Library Index")
            elif library_changed:
                debug_me(f"Reindexing '{library.title}' due to library content changes")
            elif index_expired:
                debug_me(f"Reindexing '{library.title}' because its index has expired ({elapsed_time(now - last_refresh)})")

            # Update state
            self.library_snapshots[library.title] = new_snapshot
            self.last_refresh[library.title] = now

            # Initializae index
            self.index[library.title] = {}

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
                    "type": MediaType.TV_SHOW.value if library.type == "show" else MediaType.MOVIE.value
                }
                for key in self._title_keys(item):
                    self.index[library.title].setdefault(key, []).append(entry)

            debug_me(f"Indexed {n} {MediaType.TV_SHOW.value if library.type == 'show' else MediaType.MOVIE.value} items from library {library.title}")
            return True

        return False

    def _title_keys(self, item) -> set:
        """All the normalized keys an item should be findable under."""
        keys = {normalize_title(item.title)}
        if item.slug:
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
        candidates = []

        for lib_index in self.index.values():
            candidates.extend(c for c in lib_index.get(lookup_string, []) if c["type"] in _kind)

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
