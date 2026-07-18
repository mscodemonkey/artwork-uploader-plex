from typing import Optional, Any
from core.config import Config
from core import globals
from utils import soup_utils
from utils import utils
from models.options import Options
from models.callbacks import ProcessingCallbacks
from core.exceptions import ScraperException
from core.enums import ScraperSource, FileType
from core.constants import MEDIUX_API_BASE_URL, MEDIUX_QUALITY_SUFFIX
from models.artwork_types import MovieArtworkList, TVArtworkList, CollectionArtworkList
import time

class MediuxScraper:

    def __init__(self, url: str, callbacks: Optional[ProcessingCallbacks]) -> None:
        self.soup: Optional[Any] = None
        self.url: str = url
        self.title: Optional[str] = None
        self.author: Optional[str] = None
        self.options: Options = Options()
        self.config: Config = Config()
        self.callbacks: Optional[ProcessingCallbacks] = callbacks
        self.config.load()
        self.exclusions: int = 0
        self.filtered: int = 0
        self.skipped: int = 0
        self.errored: int = 0
        self.total: int = 0

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
                    # Parse the data first to determine type
                    data_dict = utils.parse_string_to_dict(script.text)

                    if "boxset" in data_dict:
                        # This is a boxset - contains multiple sets
                        self.title = data_dict["boxset"]["name"]
                        self.author = data_dict["boxset"]["user_created"]["username"]

                        # Collect all unique set_ids from files
                        set_ids = set()
                        for set_data in data_dict["boxset"]["sets"]:
                            for file in set_data.get("files", []):
                                if file.get("set_id") and file["set_id"].get("id"):
                                    set_ids.add(file["set_id"]["id"])

                        self.callbacks.log(f"🔄 {self.title} • {self.author} | Processing {len(set_ids)} sets in boxset")
                        self.callbacks.debug(f"Obtained {len(set_ids)} set IDs from Boxset '{self.title}' by '{self.author}'")
                        self.callbacks.progress(0, 1, f"Collecting assets from MediUX boxser", "main")

                        # Spawn and scrape a child MediuxScraper for each set in the boxset
                        collected = 0
                        for n, set_id in enumerate(set_ids,1):
                            if globals.cancel_scrape:
                                break
                            self.callbacks.progress(n, len(set_ids), f"Collecting assets from MediUX boxset • {n} of {len(set_ids)} sets • {collected} assets collected", "main")
                            self._scrape_set_in_boxset(set_id)
                            movies = len(self.movie_artwork)
                            collections = len(self.collection_artwork)
                            shows = len(self.tv_artwork)                            
                            collected = movies + shows + collections
                            self.callbacks.debug(f"Processed {n} out of {len(set_ids)} sets. Collected {movies} movie, {collections} collection and {shows} TV show assets so far, skipped {self.skipped}")

                        return

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
                raise ScraperException("No poster data found in MediUX set or boxset.")

            self.skipped = self.exclusions + self.filtered + self.errored

            if self.errored > 0:
                self.callbacks.debug(f"⚠️ Encountered errors scraping {self.errored} artwork items from {self.url}")
            if self.skipped > 0:
                self.callbacks.debug(f"⏩ Skipped {self.skipped} assets(s) out of {self.total} based on exclusions ({self.exclusions}), filters ({self.filtered}) or errors ({self.errored}).")
            if self.collection_artwork:
                self.callbacks.debug(f"✅ Included {len(self.collection_artwork)} collection asset(s) for {len({item['title'] for item in self.collection_artwork})} collection(s):")
                self.callbacks.debug(self.collection_artwork)
            if self.movie_artwork:
                self.callbacks.debug(f"✅ Included {len(self.movie_artwork)} movie asset(s) for {len({item['title'] for item in self.movie_artwork})} movie(s):")
                self.callbacks.debug(self.movie_artwork)
            if self.tv_artwork:
                self.callbacks.debug(f"✅ Included {len(self.tv_artwork)} TV show asset(s) for {len({item['title'] for item in self.tv_artwork})} TV show(s):")
                self.callbacks.debug(self.tv_artwork)

            return

        except ScraperException:
            raise
        except Exception as e:
            raise ScraperException(f"Can't scrape from MediUX: {str(e)}") from e

    def _scrape_set_in_boxset(self, set_id: str) -> None:
        """
        Spawns a child MediuxScraper object for each set in the boxset and processes its artwork as if it was a single set
        appending each artwork item returned to the global artwork attributes of the parent scraper while keeping track of 
        added and skipped artwork metrics

        Args:
            set_id: The set ID to fetch

        Returns:
            Dictionary containing full set data with complete metadata, or None if fetch fails
        """
        try:
            set_url = f"https://mediux.pro/sets/{set_id}"
            self.callbacks.debug(f"Fetching full set data from {set_url}")

            child_scraper = MediuxScraper(set_url, self.callbacks)
            child_scraper.set_options(self.options)
            child_scraper.scrape()

            for artwork in child_scraper.collection_artwork:
                self.collection_artwork.append(artwork)
            for artwork in child_scraper.tv_artwork:
                self.tv_artwork.append(artwork)
            for artwork in child_scraper.movie_artwork:
                self.movie_artwork.append(artwork)

            self.skipped += child_scraper.skipped
            self.exclusions += child_scraper.exclusions
            self.filtered += child_scraper.filtered
            self.errored += child_scraper.errored
            self.total += child_scraper.total

        except Exception as e:
            self.callbacks.debug(f"Failed to scrape set {set_id}: {str(e)}")

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
        poster_data = set_data.get("files", [])

        if not poster_data:
            return  # Skip empty sets

        self.total = len(poster_data)

        if "boxset" in set_data:
            set_data.pop("boxset", None)

        # Determine media type from the keys of the set_data obtained
        show_data = set_data.get("show", None)
        movie_data = set_data.get("movie", None)
        collection_data = set_data.get("collection", None)

        # We create a show_map dict to quickly look up a season
        # or episode number based on the season_id and episode_id metadata
        # so that show_data.get(season_id) returns the season number
        # and show_data.get(episode_id) returns a tuple with the season and episode number
        if show_data:
            show_map = {}
            show_map["tmdb_id"] = show_data.get("id", 0)
            show_seasons = show_data.get("seasons", [])
            if show_seasons:
                show_map["seasons"] = {}
                show_map["episodes"] = {}
                for s in show_seasons:
                    season = s.get("season_number")
                    s_id = s.get("id")
                    show_map["seasons"][s_id] = season
                    episodes = s.get("episodes", [])
                    if episodes:
                        for ep in episodes:
                            episode = ep.get("episode_number")
                            ep_id = ep.get("id")
                            show_map["episodes"][ep_id] = (season, episode)

        # We build a collection_map dict to quickly look up the title
        # and release year of a movie inside a collection based on the movie_id
        # so that collection_map.get(movie_id).get(title) returns the title
        # and collection_map.get(movie_id).get(year) returns the year
        elif collection_data:
            collection_map = {
                m["id"]: {
                    "title": m["title"],
                    "year": m["release_date"][:4]
                } for m in collection_data.get("movies", [])
            }

        tv_sq_art = 0
        for i, poster in enumerate(poster_data):
            self.callbacks.debug(f"Processing data for poster {i+1}")
            image_stub = poster.get("id", None)
            poster_url = f"{base_url}{image_stub}{quality_suffix}{cache_buster}"
            
            file_type = poster.get("fileType", None)

            show_id_data = poster.get("show_id", None)
            is_show_cover = show_id_data is not None
            
            show_id_backdrop_data = poster.get("show_id_backdrop", None)
            is_show_backdrop = show_id_backdrop_data is not None
            
            season_id_data = poster.get("season_id", None)
            is_season_cover = season_id_data is not None
            season_id = season_id_data.get("id", None) if season_id_data else None
            
            season_id_ost_data = poster.get("season_id_ost", None)
            is_season_square_art = season_id_ost_data is not None
            
            episode_id_data = poster.get("episode_id", None)
            is_title_card = episode_id_data is not None
            episode_id = episode_id_data.get("id", None) if episode_id_data else None
            
            is_tv_show = is_show_cover or is_show_backdrop or is_season_cover or is_season_square_art or is_title_card

            movie_id_data = poster.get("movie_id", None)
            is_movie_poster = movie_id_data is not None
            
            movie_id_backdrop_data = poster.get("movie_id_backdrop", None)
            is_movie_backdrop = movie_id_backdrop_data is not None
            
            movie_id_ost_data = poster.get("movie_id_ost", None)
            is_movie_square_art = movie_id_ost_data is not None
            
            is_movie = is_movie_poster or is_movie_backdrop or is_movie_square_art
            movie_id = movie_id_data.get("id", None) if movie_id_data else \
                movie_id_backdrop_data.get("id", None) if movie_id_backdrop_data else \
                movie_id_ost_data.get("id", None) if movie_id_ost_data else None

            collection_id_data = poster.get("collection_id", None)
            is_collection_poster = collection_id_data is not None
            is_collection_backdrop = collection_id_data is None and file_type == FileType.BACKDROP.value and not is_movie_backdrop and not is_show_backdrop
            is_collection_square_art = collection_id_data is None and file_type == FileType.ALBUM_ART.value and not is_movie_square_art and not is_season_square_art
            is_collection = is_collection_poster or is_collection_backdrop or is_collection_square_art

            if is_tv_show:
                show_id = show_map["tmdb_id"]
                show_name = show_data["name"]
                year = show_data["first_air_date"][:4]
                
                if is_show_cover: # This is a show cover
                    file_type = FileType.SHOW_COVER.value
                    season = "Cover"
                    episode = None
                    self.callbacks.debug(f"Detected show cover")

                elif is_season_cover: # This is a season cover
                    file_type = FileType.SEASON_COVER.value
                    if season_id in show_map["seasons"]:
                        season = show_map["seasons"][season_id]
                        episode = "Cover"
                        self.callbacks.debug(f"Detected season cover for S{season:02}")
                    else:
                        self.callbacks.debug(f"⏩ Skipping season cover - incorrect season metadata")
                        self.callbacks.log(f"⚠️ {show_name} ({year}) • {self.author} | Skipping season cover - incorrect season metadata")
                        self.errored += 1
                        continue
                
                elif is_show_backdrop: # This is a show background
                    file_type = FileType.BACKGROUND.value
                    season = "Backdrop"
                    episode = None
                    self.callbacks.debug(f"Detected show backdrop")
                
                elif is_season_square_art: # This is a square art asset
                    file_type = FileType.SQUARE_ART.value
                    season = f"SquareArt_{tv_sq_art}" # We tag each square art asset with a sequential number starting at 0
                    episode = None
                    tv_sq_art += 1
                    self.callbacks.debug(f"Detected square art for season S{season:02}")
                
                elif is_title_card: # This is a title card
                    file_type = FileType.TITLE_CARD.value
                    if episode_id in show_map["episodes"]:
                        (season, episode) = show_map["episodes"][episode_id]
                        self.callbacks.debug(f"Detected title card for S{season:02}E{episode:02}")
                    else:
                        self.callbacks.debug(f"⏩ Skipping title card - incorrect episode metadata")
                        self.callbacks.log(f"⚠️ {show_name} ({year}) • {self.author} | Skipping title card - incorrect episode metadata")
                        self.errored += 1
                        continue
                
                else:
                    self.callbacks.debug(f"⏩ Skipping TV Show asset - missing metadata")
                    self.callbacks.log(f"⚠️ {show_name} ({year}) • {self.author} | Skipping TV Show asset - missing metadata")
                    self.errored += 1
                    continue

                # Apply filters and exclusions
                if (self.options.has_no_filters() and file_type in self.config.mediux_filters) or self.options.has_filter(file_type):
                    if not self.options.is_excluded(image_stub, season if isinstance(season, int) else None, episode if isinstance(episode, int) else None):
                        self.callbacks.debug(
                            f"{i+1}. ✅ Including {file_type.replace('_', ' ')} for '{show_name} ({year})'"
                            + (f", Season {season}" if isinstance(season, int) else "")
                            + (f", Episode {episode}" if isinstance(episode, int) else "")
                            + "."
                        )
                        tv_artwork = {}
                        tv_artwork["title"] = show_name
                        tv_artwork["season"] = season
                        tv_artwork["episode"] = episode
                        tv_artwork["url"] = poster_url
                        tv_artwork["source"] = ScraperSource.MEDIUX.value
                        tv_artwork["year"] = int(year)
                        tv_artwork["id"] = image_stub
                        tv_artwork["file_type"] = file_type
                        tv_artwork["author"] = self.author
                        tv_artwork["tmdb_id"] = show_id
                        self.tv_artwork.append(tv_artwork)
                    else:
                        self.exclusions += 1
                        self.callbacks.debug(
                            f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{show_name} ({year})'"
                            + (f", Season {season}" if isinstance(season, int) else "")
                            + (f", Episode {episode}" if isinstance(episode, int) else "")
                            + " based on exclusions."
                        )
                else:
                    self.filtered += 1
                    self.callbacks.debug(
                        f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{show_name} ({year})'"
                        + (f", Season {season}" if isinstance(season, int) else "")
                        + (f", Episode {episode}" if isinstance(episode, int) else "")
                        + " based on filters."
                    )

            elif is_movie:
                # If it's a movie set, we obtain title and year directly from the set metadata
                if movie_data:
                    title = movie_data["title"]
                    year = movie_data["release_date"][:4]
                
                # If it's a collection set, we obtain movie title and year from the collection map we built earlier
                elif collection_data:
                    title = collection_map[movie_id]["title"]
                    year = collection_map[movie_id]["year"]

                else:
                    self.callbacks.debug(f"⏩ Skipping asset - missing metadata")
                    self.callbacks.log(f"⚠️ {self.title} • {self.author} | Skipping asset - missing metadata")
                    self.errored += 1
                    continue        
                
                if is_movie_poster: # This is a movie poster
                    file_type = FileType.MOVIE_POSTER.value
                    self.callbacks.debug("Detected movie poster")
                
                elif is_movie_backdrop: # This is a movie bacground
                    file_type = FileType.BACKGROUND.value
                    self.callbacks.debug("Detected movie backdrop")

                elif is_movie_square_art: # This is a movie square asset
                    file_type = FileType.SQUARE_ART.value
                    self.callbacks.debug("Decteted movie square art")

                else:
                    self.callbacks.debug(f"⏩ Skipping movie asset - missing metadata")
                    self.callbacks.log(f"⚠️ {title} ({year}) • {self.author} | Skipping movie asset - missing metadata")
                    self.errored += 1
                    continue                    

                if (self.options.has_no_filters() and file_type in self.config.mediux_filters) or self.options.has_filter(file_type):
                    if not self.options.is_excluded(image_stub):
                        self.callbacks.debug(f"{i+1}. ✅ Including {file_type.replace('_', ' ')} for '{title} ({year})'.")
                        movie_artwork = {}
                        movie_artwork["title"] = title
                        movie_artwork["year"] = int(year)
                        movie_artwork["url"] = poster_url
                        movie_artwork["source"] = ScraperSource.MEDIUX.value
                        movie_artwork["id"] = image_stub
                        movie_artwork["file_type"] = file_type
                        movie_artwork["author"] = self.author
                        movie_artwork["tmdb_id"] = movie_id
                        self.movie_artwork.append(movie_artwork)
                    else:
                        self.exclusions += 1
                        self.callbacks.debug(f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{title} ({year})' based on exclusions.")
                else:
                    self.filtered += 1
                    self.callbacks.debug(f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{title} ({year})' based on filters.")                
            
            elif is_collection:
                title = collection_data["collection_name"]
                if is_collection_poster: # This is a collection poster
                    file_type = FileType.COLLECTION_POSTER.value
                    self.callbacks.debug("Detectec collection poster")
                
                elif is_collection_backdrop: # This is a collection background
                    file_type = FileType.BACKGROUND.value
                    self.callbacks.debug("Dectected collection backdrop")

                elif is_collection_square_art: # This is a qcollection square asset
                    file_type = FileType.SQUARE_ART.value
                    self.callbacks.debug("Dected collection square art")

                if (self.options.has_no_filters() and file_type in self.config.mediux_filters) or self.options.has_filter(file_type):
                    if not self.options.is_excluded(image_stub):
                        self.callbacks.debug(f"{i+1}. ✅ Including {file_type.replace('_', ' ')} for '{title}'.")
                        collection_artwork = {}
                        collection_artwork["title"] = title
                        collection_artwork["url"] = poster_url
                        collection_artwork["id"] = image_stub
                        collection_artwork["source"] = ScraperSource.MEDIUX.value
                        collection_artwork["file_type"] = file_type
                        collection_artwork["year"] = None
                        collection_artwork["author"] = self.author
                        self.collection_artwork.append(collection_artwork)
                    else:
                        self.exclusions += 1
                        self.callbacks.debug(f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{title}' based on exclusions.")
                else:
                    self.filtered += 1
                    self.callbacks.debug(f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{title}' based on filters.")

            else:
                self.callbacks.debug(f"⏩ Skipping asset - missing metadata")
                self.callbacks.log(f"⚠️ {self.title} • {self.author} | Skipping asset - missing metadata")
                self.errored += 1
                continue