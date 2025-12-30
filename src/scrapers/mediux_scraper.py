from utils.notifications import debug_me
from utils import utils
from utils import soup_utils
from models.options import Options
from models.artwork_types import MovieArtworkList, TVArtworkList, CollectionArtworkList
from core.exceptions import ScraperException
from core.enums import MediaType, ScraperSource, FileType
from core.constants import (
    ANSI_BOLD, ANSI_RESET, BOOTSTRAP_COLORS,
    MEDIUX_API_BASE_URL, MEDIUX_BASE_URL, MEDIUX_QUALITY_SUFFIX,
    SEASON_COVER, SEASON_BACKDROP, EPISODE_COVER
)
from core import globals
import time
from pprint import pformat
from typing import Optional, Any
from logging_config import get_logger

logger = get_logger(__name__)


class MediuxScraper:

    def __init__(self, url: str) -> None:
        self.soup: Optional[Any] = None
        self.url: str = url
        self.title: Optional[str] = None
        self.author: Optional[str] = None
        self.options: Options = Options()
        self.exclusions: int = 0

        self.movie_artwork: MovieArtworkList = []
        self.tv_artwork: TVArtworkList = []
        self.collection_artwork: CollectionArtworkList = []

    # Set options - otherwise will use defaults of False
    def set_options(self, options: Options) -> None:
        self.options = options

    def scrape(self) -> int:

        try:
            self.soup = soup_utils.cook_soup(self.url)
        except Exception as e:
            raise ScraperException(
                f"Can't scrape from MediUX: {str(e)}") from e

        scripts = self.soup.find_all('script')

        try:
            data_dict = None
            for script in scripts:
                if 'files' in script.text:
                    # Parse the data first to determine type
                    data_dict = utils.parse_string_to_dict(script.text)

                    if "boxset" in data_dict:
                        # This is a boxset - contains multiple sets
                        self.title = data_dict["boxset"]["name"]
                        self.author = data_dict["boxset"]["user_created"]["username"]

                        # Build cache of full set data for boxsets
                        # Collect all unique set_ids from files
                        set_ids = set()
                        for set_data in data_dict["boxset"]["sets"]:
                            for file in set_data.get("files", []):
                                if file.get("set_id") and file["set_id"].get("id"):
                                    set_ids.add(file["set_id"]["id"])

                        # Fetch full set data for each unique set_id
                        full_set_cache = {}
                        for set_id in set_ids:
                            full_data = self._fetch_full_set_data(set_id)
                            if full_data:
                                full_set_cache[set_id] = full_data

                        # Process each set in the boxset with the cache
                        for set_data in data_dict["boxset"]["sets"]:
                            self._process_set(set_data, full_set_cache)
                        break
                    elif "set" in data_dict:
                        if 'Set Link\\' not in script.text:
                            # This is a regular set
                            if data_dict["set"]["show"] is not None:
                                self.title = f"{data_dict["set"]["show"]["name"]} ({data_dict["set"]["show"]["first_air_date"][:4]})"
                            elif data_dict["set"]["movie"] is not None:
                                self.title = f"{data_dict["set"]["movie"]["title"]} ({data_dict["set"]["movie"]["release_date"][:4]})"
                            elif data_dict["set"]["collection"] is not None:
                                self.title = data_dict["set"]["collection"]["collection_name"]

                            self.author = data_dict["set"]["user_created"]["username"]

                            # Process the single set
                            self._process_set(data_dict["set"])
                            break

            if not data_dict:
                raise ScraperException(
                    "No poster data found in MediUX set or boxset.")

            if globals.debug:
                if self.collection_artwork:
                    debug_me(
                        f"Found {len(self.collection_artwork)} collection asset(s) for {len({item['title'] for item in self.collection_artwork})} collection(s):",
                        "MediuxScraper/scrape")
                    logger.debug(
                        f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('success').get('ansi')}*************************************************************")
                    logger.debug(pformat(self.collection_artwork))
                    logger.debug(
                        f"*************************************************************{ANSI_RESET}")
                if self.movie_artwork:
                    debug_me(
                        f"Found {len(self.movie_artwork)} movie asset(s) for {len({item['title'] for item in self.movie_artwork})} movie(s):",
                        "MediuxScraper/scrape")
                    logger.debug(
                        f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('success').get('ansi')}*************************************************************")
                    logger.debug(pformat(self.movie_artwork))
                    logger.debug(
                        f"*************************************************************{ANSI_RESET}")
                if self.tv_artwork:
                    debug_me(
                        f"Skipped {self.exclusions} assets(s) based on exclusions.", "MediuxScraper/scrape")
                    debug_me(
                        f"Found {len(self.tv_artwork)} TV show asset(s) for {len({item['title'] for item in self.tv_artwork})} TV show(s):",
                        "MediuxScraper/scrape")
                    logger.debug(
                        f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('success').get('ansi')}*************************************************************")
                    logger.debug(pformat(self.tv_artwork))
                    logger.debug(
                        f"*************************************************************{ANSI_RESET}")

            # Return the number of excluded assets
            return self.exclusions

        except ScraperException:
            raise
        except Exception as e:
            raise ScraperException(
                f"Can't scrape from MediUX: {str(e)}") from e

    @staticmethod
    def _fetch_full_set_data(set_id: str) -> Optional[dict]:
        """
        Fetch full set data from MediUX for a given set ID.
        This is used to get complete metadata for boxset files.

        Args:
            set_id: The set ID to fetch

        Returns:
            Dictionary containing full set data with complete metadata, or None if fetch fails
        """
        try:
            set_url = f"{MEDIUX_BASE_URL}/sets/{set_id}"
            debug_me(
                f"Fetching full set data from {set_url}", "MediuxScraper/_fetch_full_set_data")

            set_soup = soup_utils.cook_soup(set_url)
            scripts = set_soup.find_all('script')

            for script in scripts:
                if 'set' in script.text and 'files' in script.text and 'Set Link\\' not in script.text:
                    data_dict = utils.parse_string_to_dict(script.text)
                    if 'set' in data_dict:
                        return data_dict['set']

            return None
        except Exception as e:
            debug_me(
                f"Failed to fetch set {set_id}: {str(e)}", "MediuxScraper/_fetch_full_set_data")
            return None

    def _process_set(self, set_data: dict, full_set_cache: Optional[dict] = None) -> None:
        """
        Process a single set's data and extract artwork.
        This method is used for both individual sets and sets within boxsets.

        Args:
            set_data: Dictionary containing set information (show/movie/collection and files)
            full_set_cache: Optional cache of full set data keyed by set_id (for boxsets)
        """
        base_url = MEDIUX_API_BASE_URL
        quality_suffix = MEDIUX_QUALITY_SUFFIX
        cache_buster = f"&_cb={int(time.time())}"
        poster_data = set_data.get("files", [])

        if not poster_data:
            return  # Skip empty sets

        # Determine media type from first file with relevant IDs
        for data in poster_data:
            if data.get("show_id") is not None or data.get("show_id_backdrop") is not None or \
                    data.get("episode_id") is not None or data.get("season_id") is not None:
                media_type = MediaType.TV_SHOW.value
                break
        else:
            media_type = MediaType.MOVIE.value

        # Process each file in the set
        for data in poster_data:
            # debug_me(str(data["id"]),"MediuxScraper/_process_set")

            if media_type == MediaType.TV_SHOW.value:

                # Boxsets don't include full seasons data, regular sets do
                seasons = set_data.get("show", {}).get("seasons", [])
                show_name = set_data["show"]["name"]
                show_id = set_data["show"].get("id", None)

                try:
                    year = int(set_data["show"].get("first_air_date", "")[:4])
                except (KeyError, ValueError, TypeError, IndexError):
                    year = None

                # If year is missing, and we have a cache, try to get it from there
                if year is None and full_set_cache and data.get("set_id"):
                    set_id = data["set_id"]["id"]
                    if set_id in full_set_cache:
                        full_set = full_set_cache[set_id]
                        try:
                            year = int(full_set.get("show", {}).get(
                                "first_air_date", "")[:4])
                        except (KeyError, ValueError, TypeError, IndexError):
                            pass

                if data["fileType"] == FileType.TITLE_CARD.value:
                    # Check if this is from a boxset with cached full set data
                    if full_set_cache and data.get("set_id") and data["set_id"].get("id"):
                        set_id = data["set_id"]["id"]
                        file_id = data["id"]

                        # Look up this file in the cached full set data
                        if set_id in full_set_cache:
                            full_set = full_set_cache[set_id]
                            # Find the matching file by ID in the full set data
                            matching_file = next((f for f in full_set.get(
                                "files", []) if f.get("id") == file_id), None)

                            if matching_file and "title" in matching_file:
                                # Use the full metadata from the cached set
                                season = matching_file["episode_id"]["season_id"]["season_number"]
                                title = matching_file["title"]
                                try:
                                    episode = int(title.rsplit(" E", 1)[1])
                                except (IndexError, ValueError):
                                    debug_me(
                                        f"Error getting episode number for {title}.", "MediuxScraper/_process_set")
                                    episode = None
                                file_type = FileType.TITLE_CARD.value
                            else:
                                # Fallback to partial data if full metadata not found
                                if data.get("episode_id") and data["episode_id"].get("season_id"):
                                    season = data["episode_id"]["season_id"]["season_number"]
                                    episode = None
                                    file_type = FileType.TITLE_CARD.value
                                else:
                                    debug_me(f"Skipping title card - no metadata in cache",
                                             "MediuxScraper/_process_set")
                                    continue
                        else:
                            # Set not in cache, use partial data
                            if data.get("episode_id") and data["episode_id"].get("season_id"):
                                season = data["episode_id"]["season_id"]["season_number"]
                                episode = None
                                file_type = FileType.TITLE_CARD.value
                            else:
                                debug_me(
                                    f"Skipping title card - set not in cache", "MediuxScraper/_process_set")
                                continue

                    # Regular sets have full episode metadata with title
                    elif "title" in data:
                        data.get("episode_id", {}).get("id")
                        season = data["episode_id"]["season_id"]["season_number"]
                        title = data["title"]
                        try:
                            episode = int(title.rsplit(" E", 1)[1])
                        except (IndexError, ValueError):
                            debug_me(
                                f"Error getting episode number for {title}.", "MediuxScraper/_process_set")
                            episode = None
                        file_type = FileType.TITLE_CARD.value

                    else:
                        # No usable metadata, skip
                        debug_me(
                            f"Skipping title card - missing episode metadata", "MediuxScraper/_process_set")
                        continue

                elif data["fileType"] == FileType.BACKDROP.value:
                    # Check if we can get backdrop metadata from cache
                    show_id_backdrop = data.get("show_id_backdrop")

                    if not show_id_backdrop and full_set_cache and data.get("set_id"):
                        # Try to get from cached full set data
                        set_id = data["set_id"]["id"]
                        file_id = data["id"]

                        if set_id in full_set_cache:
                            full_set = full_set_cache[set_id]
                            matching_file = next((f for f in full_set.get(
                                "files", []) if f.get("id") == file_id), None)
                            if matching_file:
                                show_id_backdrop = matching_file.get(
                                    "show_id_backdrop")

                    if show_id_backdrop is not None:
                        debug_me(f"Backdrop: {show_id_backdrop}",
                                 "MediuxScraper/_process_set")
                        season = SEASON_BACKDROP
                        episode = None
                        file_type = "background"
                    else:
                        debug_me(
                            f"Skipping backdrop - missing show_id_backdrop", "MediuxScraper/_process_set")
                        continue

                elif data["fileType"] == FileType.POSTER.value:
                    # Posters can be show covers or season covers
                    # Try to get full metadata from cache if needed
                    # Note: file_show_id is just used to determine poster type, NOT for tmdb_id
                    file_show_id = data.get("show_id")
                    season_id_data = data.get("season_id")

                    # If boxset data is missing metadata, try cache
                    if (not file_show_id or not season_id_data) and full_set_cache and data.get("set_id"):
                        set_id = data["set_id"]["id"]
                        file_id = data["id"]

                        if set_id in full_set_cache:
                            full_set = full_set_cache[set_id]
                            matching_file = next((f for f in full_set.get(
                                "files", []) if f.get("id") == file_id), None)
                            if matching_file:
                                if not file_show_id:
                                    file_show_id = matching_file.get("show_id")
                                if not season_id_data:
                                    season_id_data = matching_file.get(
                                        "season_id")
                                # Also update seasons array from cached data if needed
                                if not seasons:
                                    seasons = full_set.get(
                                        "show", {}).get("seasons", [])

                    # Determine if this is a show cover or season cover
                    if season_id_data:
                        # This is a season cover
                        debug_me(
                            f"Season cover: {season_id_data}", "MediuxScraper/_process_set")
                        # Try to get season number from seasons array if available
                        if seasons:
                            season_id = season_id_data.get("id")
                            if season_id:
                                season_data = [
                                    s for s in seasons if s["id"] == season_id]
                                if season_data:
                                    season = season_data[0]["season_number"]
                                else:
                                    season = season_id_data.get(
                                        "season_number", 0)
                            else:
                                season = season_id_data.get("season_number", 0)
                        else:
                            # No seasons array, get directly from season_id
                            season = season_id_data.get("season_number", 0)
                        episode = EPISODE_COVER
                        file_type = "season_cover"
                    elif file_show_id is not None:
                        # This is a show cover
                        debug_me(f"Show cover detected",
                                 "MediuxScraper/_process_set")
                        season = SEASON_COVER
                        episode = None
                        file_type = "show_cover"
                    else:
                        debug_me(
                            f"Skipping poster - missing show_id and season_id", "MediuxScraper/_process_set")
                        continue

                else:
                    # Unknown file type or structure, skip
                    debug_me(f"Skipping unknown TV show file type: {data.get('fileType')}",
                             "MediuxScraper/_process_set")
                    continue

            elif media_type == MediaType.MOVIE.value:

                if data["movie_id"]:
                    movie_id = data["movie_id"]["id"]
                    if set_data.get("movie"):
                        # This is a movie poster
                        title = set_data["movie"]["title"]
                        year = int(set_data["movie"]["release_date"][:4])
                        file_type = "poster"
                    elif set_data.get("collection"):
                        # This is a movie poster inside a collection set
                        movies = set_data["collection"]["movies"]
                        movie_data = [
                            movie for movie in movies if movie["id"] == movie_id][0]
                        title = movie_data["title"]
                        year = int(movie_data["release_date"][:4])
                        file_type = "poster"
                elif data["collection_id"]:
                    # This is a collection poster
                    title = set_data["collection"]["collection_name"]
                    file_type = "collection poster"
                else:
                    if data["fileType"] == "poster":
                        # This is a collection poster
                        file_type = "collection poster"
                        title = set_data["collection"]["collection_name"]
                    elif data["fileType"] == "backdrop":
                        # This is a movie background
                        if data["movie_id_backdrop"]:
                            movie_id = data["movie_id_backdrop"]["id"]
                            if set_data.get("collection") is not None:
                                movies = set_data["collection"]["movies"]
                                movie_data = [
                                    movie for movie in movies if movie["id"] == movie_id][0]
                            else:
                                movie_data = set_data["movie"]
                            title = movie_data["title"]
                            year = int(movie_data["release_date"][:4])
                            file_type = "background"
                        else:
                            # The only remaining artwork can be the collection background
                            title = set_data["collection"]["collection_name"]
                            file_type = "background"

            image_stub = data["id"]
            poster_url = f"{base_url}{image_stub}{quality_suffix}{cache_buster}"

            if media_type == MediaType.TV_SHOW.value:
                if not self.options.is_excluded(image_stub, season if isinstance(season, int) else None,
                                                episode if isinstance(episode, int) else None):
                    tv_artwork = {}
                    tv_artwork["title"] = show_name
                    tv_artwork["season"] = season
                    tv_artwork["episode"] = episode
                    tv_artwork["url"] = poster_url
                    tv_artwork["source"] = ScraperSource.MEDIUX.value
                    tv_artwork["year"] = year
                    tv_artwork["id"] = image_stub
                    tv_artwork['type'] = file_type
                    tv_artwork["author"] = self.author
                    tv_artwork["tmdb_id"] = show_id
                    # debug_me(f"TV Artwork: {tv_artwork}", "MediuxScraper/_process_set")
                    self.tv_artwork.append(tv_artwork)
                else:
                    self.exclusions += 1
                    if episode == "Cover":
                        debug_me(
                            f"Skipping season cover for '{show_name} ({year})', Season {season} based on exclusions.",
                            "MediuxScraper/_process_set")
                    else:
                        debug_me(
                            f"Skipping title card for '{show_name} ({year})', Season {season}, Episode {episode} based on exclusions.",
                            "MediuxScraper/_process_set")

            elif media_type == MediaType.MOVIE.value:
                if "Collection" in title:
                    collection_artwork = {}
                    collection_artwork["title"] = title
                    collection_artwork["url"] = poster_url
                    collection_artwork["id"] = image_stub
                    collection_artwork["source"] = ScraperSource.MEDIUX.value
                    collection_artwork["type"] = file_type
                    collection_artwork["year"] = None
                    collection_artwork["author"] = self.author
                    # debug_me(f"Collection Artwork: {collection_artwork}", "MediuxScraper/_process_set")
                    self.collection_artwork.append(collection_artwork)
                else:
                    movie_artwork = {}
                    movie_artwork["title"] = title
                    movie_artwork["year"] = int(year)
                    movie_artwork["url"] = poster_url
                    movie_artwork["source"] = ScraperSource.MEDIUX.value
                    movie_artwork["id"] = image_stub
                    movie_artwork["type"] = file_type
                    movie_artwork["author"] = self.author
                    movie_artwork["tmdb_id"] = movie_id
                    # debug_me(f"Movie Artwork: {movie_artwork}", "MediuxScraper/_process_set")
                    self.movie_artwork.append(movie_artwork)
