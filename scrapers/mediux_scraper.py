from typing import Optional, Any
from core import globals
from pprint import pprint
from utils import soup_utils
from utils import utils
from utils.notifications import debug_me
from models.options import Options
from core.exceptions import ScraperException
from core.enums import MediaType, ScraperSource, FileType
from core.constants import ANSI_BOLD, ANSI_RESET, BOOTSTRAP_COLORS, MEDIUX_API_BASE_URL, MEDIUX_QUALITY_SUFFIX
from models.artwork_types import MovieArtworkList, TVArtworkList, CollectionArtworkList
import time

class MediuxScraper:

    def __init__(self, url: str) -> None:
        self.soup: Optional[Any] = None
        self.url: str = url
        self.title: Optional[str] = None
        self.author: Optional[str] = None
        self.options: Options = Options()

        self.movie_artwork: MovieArtworkList = []
        self.tv_artwork: TVArtworkList = []
        self.collection_artwork: CollectionArtworkList = []


    # Set options - otherwise will use defaults of False
    def set_options(self, options: Options) -> None:
        self.options = options


    def scrape(self) -> None:

        try:
            self.soup = soup_utils.cook_soup(self.url)
        except Exception as e:
            raise ScraperException(f"Can't scrape from MediUX: {str(e)}") from e

        scripts = self.soup.find_all('script')

        try:
            data_dict = None
            for script in scripts:
                if 'files' in script.text:
                    if 'boxset' in script.text:
                        # This is a boxset - contains multiple sets
                        data_dict = utils.parse_string_to_dict(script.text)
                        self.title = data_dict["boxset"]["name"]
                        self.author = data_dict["boxset"]["user_created"]["username"]

                        # Process each set in the boxset
                        for set_data in data_dict["boxset"]["sets"]:
                            self._process_set(set_data)
                        break
                    elif 'set' in script.text:
                        if 'Set Link\\' not in script.text:
                            # This is a regular set
                            data_dict = utils.parse_string_to_dict(script.text)

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
                raise ScraperException("No poster data found in MediUX set or boxset.")

            if globals.debug:
                if self.collection_artwork:
                    debug_me(f"Found {len(self.collection_artwork)} collection asset(s) for {len({item['title'] for item in self.collection_artwork})} collection(s):", "MediuxScraper/scrape")
                    print(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('success').get('ansi')}*************************************************************")
                    pprint(self.collection_artwork)
                    print(f"*************************************************************{ANSI_RESET}")
                if self.movie_artwork:
                    debug_me(f"Found {len(self.movie_artwork)} movie asset(s) for {len({item['title'] for item in self.movie_artwork})} movie(s):","MediuxScraper/scrape")
                    print(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('success').get('ansi')}*************************************************************")
                    pprint(self.movie_artwork)
                    print(f"*************************************************************{ANSI_RESET}")
                if self.tv_artwork:
                    debug_me(f"Found {len(self.tv_artwork)} TV show asset(s) for {len({item['title'] for item in self.tv_artwork})} TV show(s):", "MediuxScraper/scrape")
                    print(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('success').get('ansi')}*************************************************************")
                    pprint(self.tv_artwork)
                    print(f"*************************************************************{ANSI_RESET}")

        except ScraperException:
            raise
        except Exception as e:
            raise ScraperException(f"Can't scrape from MediUX: {str(e)}") from e


    def _process_set(self, set_data: dict) -> None:
        """
        Process a single set's data and extract artwork.
        This method is used for both individual sets and sets within boxsets.

        Args:
            set_data: Dictionary containing set information (show/movie/collection and files)
        """
        base_url = MEDIUX_API_BASE_URL
        quality_suffix = MEDIUX_QUALITY_SUFFIX
        cache_buster = f"&_cb={int(time.time())}"
        media_type = None
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
            debug_me(str(data["id"]),"MediuxScraper/_process_set")

            if media_type == MediaType.TV_SHOW.value:

                # Boxsets don't include full seasons data, regular sets do
                seasons = set_data.get("show", {}).get("seasons", [])
                show_name = set_data["show"]["name"]
                show_id = set_data["show"].get("id", None)

                try:
                    year = int(set_data["show"].get("first_air_date", "")[:4])
                except (KeyError, ValueError, TypeError, IndexError):
                    year = None

                if data["fileType"] == FileType.TITLE_CARD.value:
                    # Box sets have simplified episode_id structure without full metadata
                    # Skip title cards in boxsets as they lack episode identification
                    if "title" not in data:
                        debug_me(f"Skipping title card from boxset - missing episode metadata", "MediuxScraper/_process_set")
                        continue

                    episode_id = data.get("episode_id", {}).get("id")
                    season = data["episode_id"]["season_id"]["season_number"]
                    title = data["title"]
                    try:
                        episode = int(title.rsplit(" E", 1)[1])
                    except (IndexError, ValueError):
                        debug_me(f"Error getting episode number for {title}.", "MediuxScraper/_process_set")
                        episode = None

                    file_type = FileType.TITLE_CARD.value

                elif data["fileType"] == FileType.BACKDROP.value and data.get("show_id_backdrop") is not None:
                    debug_me(f"Backdrop: {data['show_id_backdrop']}", "MediuxScraper/_process_set")
                    season = "Backdrop"
                    episode = None
                    file_type = "background"

                elif data["fileType"] == FileType.POSTER.value and data.get("season_id") is None:
                    # Skip if missing show_id (can happen in boxsets)
                    if "show_id" not in data or data.get("show_id") is None:
                        debug_me(f"Skipping show cover from boxset - missing show_id", "MediuxScraper/_process_set")
                        continue
                    debug_me(f"Cover: {data.get('show_id')}", "MediuxScraper/_process_set")
                    season = "Cover"
                    episode = None
                    file_type = "show_cover"

                elif data["fileType"] == FileType.POSTER.value and data.get("season_id") is not None:
                    debug_me(f"Season cover: {data['season_id']}", "MediuxScraper/_process_set")
                    # Try to get season number from seasons array if available, otherwise from season_id directly
                    if seasons:
                        season_id = data["season_id"].get("id")
                        if season_id:
                            season_data = [s for s in seasons if s["id"] == season_id]
                            if season_data:
                                season = season_data[0]["season_number"]
                            else:
                                season = data["season_id"].get("season_number", 0)
                        else:
                            season = data["season_id"].get("season_number", 0)
                    else:
                        # Boxsets don't have seasons array, get directly from season_id
                        season = data["season_id"].get("season_number", 0)
                    episode = "Cover"
                    file_type = "season_cover"

                else:
                    # Unknown file type or structure, skip
                    debug_me(f"Skipping unknown TV show file type: {data.get('fileType')}", "MediuxScraper/_process_set")
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
                        movie_data = [movie for movie in movies if movie["id"] == movie_id][0]
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
                                movie_data = [movie for movie in movies if movie["id"] == movie_id][0]
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