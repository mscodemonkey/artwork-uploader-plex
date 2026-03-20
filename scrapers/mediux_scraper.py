from typing import Optional, Any
from core.config import Config
from utils import soup_utils
from utils import utils
from models.options import Options
from models.callbacks import ProcessingCallbacks
from core.exceptions import ScraperException
from core.enums import MediaType, ScraperSource, FileType
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

                        # Build cache of full set data for boxsets
                        # Collect all unique set_ids from files
                        set_ids = set()
                        for set_data in data_dict["boxset"]["sets"]:
                            for file in set_data.get("files", []):
                                if file.get("set_id") and file["set_id"].get("id"):
                                    set_ids.add(file["set_id"]["id"])

                        self.callbacks.log(f"🔄 {self.title} • {self.author} | Processing {len(set_ids)} sets in boxset")
                        #self.callbacks.status(f"Scraping sets in MediUX boxset {self.title} by {self.author}", color="info", sticky=True, spinner=True)
                        self.callbacks.debug(f"Obtained {len(set_ids)} set IDs from Boxset '{self.title}' by '{self.author}'", "MedixScraper/scrape")
                        self.callbacks.progress(0, 1, f"Collecting assets from MediUX boxser", "main")

                        # Spawn and scrape a child MediuxScraper for each set in the boxset
                        collected = 0
                        for n, set_id in enumerate(set_ids,1):
                            #self.callbacks.status(f"Scraping sets in MediUX boxset {self.title} by {self.author}", color="info", sticky=True, spinner=True)
                            self.callbacks.progress(n, len(set_ids), f"Collecting assets from MediUX boxset • {n} of {len(set_ids)} sets • {collected} assets collected", "main")
                            self._scrape_set_in_boxset(set_id)
                            movies = len(self.movie_artwork)
                            collections = len(self.collection_artwork)
                            shows = len(self.tv_artwork)                            
                            collected = movies + shows + collections
                            self.callbacks.debug(f"Processed {n} out of {len(set_ids)} sets. Collected {movies} movie, {collections} collection and {shows} TV show assets so far, skipped {self.skipped}", "MedixScraper/scrape")

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
                self.callbacks.debug(f"⚠️ Encountered errors scraping {self.errored} artwork items from {self.url}", "MediuxScraper/scrape")
            if self.skipped > 0:
                self.callbacks.debug(f"⏩ Skipped {self.skipped} assets(s) out of {self.total} based on exclusions ({self.exclusions}), filters ({self.filtered}) or errors ({self.errored}).", "MediuxScraper/scrape")
            if self.collection_artwork:
                self.callbacks.debug(f"✅ Included {len(self.collection_artwork)} collection asset(s) for {len({item['title'] for item in self.collection_artwork})} collection(s):", "MediuxScraper/scrape")
                self.callbacks.debug(f"*************************************************************")
                self.callbacks.debug(self.collection_artwork)
                self.callbacks.debug(f"*************************************************************")  
            if self.movie_artwork:
                self.callbacks.debug(f"✅ Included {len(self.movie_artwork)} movie asset(s) for {len({item['title'] for item in self.movie_artwork})} movie(s):","MediuxScraper/scrape")
                self.callbacks.debug(f"*************************************************************")
                self.callbacks.debug(self.movie_artwork)
                self.callbacks.debug(f"*************************************************************")
            if self.tv_artwork:
                self.callbacks.debug(f"✅ Included {len(self.tv_artwork)} TV show asset(s) for {len({item['title'] for item in self.tv_artwork})} TV show(s):", "MediuxScraper/scrape")
                self.callbacks.debug(f"*************************************************************")
                self.callbacks.debug(self.tv_artwork)
                self.callbacks.debug(f"*************************************************************")

            #self.callbacks.log(f"📍 {self.title} • {self.author} | Fetched {self.total} asset(s) from MediUX")

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
            self.callbacks.debug(f"Fetching full set data from {set_url}", "MediuxScraper/_scrape_set_in_boxset")

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
            self.callbacks.debug(f"Failed to scrape set {set_id}: {str(e)}", "MediuxScraper/_scrape_set_in_boxset")


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
        self.total=len(poster_data)

        for i, data in enumerate(poster_data):
            #self.callbacks.debug(str(data["id"]),"MediuxScraper/_process_set")

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
                    # Regular sets have full episode metadata with title
                    if "title" in data:
                        season = data["episode_id"]["season_id"]["season_number"]
                        title = data["title"]
                        try:
                            episode = int(title.rsplit(" E", 1)[1])
                        except (IndexError, ValueError):
                            self.callbacks.debug(f"Error getting episode number for {title}.", "MediuxScraper/_process_set")
                            episode = None
                        file_type = FileType.TITLE_CARD.value
                        self.callbacks.debug(f"Found title card for season {season} episode {episode}", "MediuxScraper/_process_set")

                    else:
                        # No usable metadata, skip
                        self.callbacks.debug(f"⏩ Skipping title card - missing episode metadata", "MediuxScraper/_process_set")
                        self.callbacks.log(f"⚠️ {self.title} • {self.author} | Skipping title card (missing necessary metadata from MediUX)")
                        self.errored += 1
                        continue

                elif data["fileType"] == FileType.BACKDROP.value:

                    show_id_backdrop = data.get("show_id_backdrop")

                    if show_id_backdrop is not None:
                        self.callbacks.debug(f"Backdrop: {show_id_backdrop}", "MediuxScraper/_process_set")
                        season = "Backdrop"
                        episode = None
                        file_type = "background"
                    else:
                        self.callbacks.debug(f"⏩ Skipping backdrop - missing show_id_backdrop", "MediuxScraper/_process_set")
                        self.callbacks.log(f"⚠️ {self.title} • {self.author} | Skipping backdrop (missing necessary metadata from MediUX)")
                        self.errored += 1
                        continue

                elif data["fileType"] == FileType.POSTER.value:
                    # Posters can be show covers or season covers
                    # Note: file_show_id is just used to determine poster type, NOT for tmdb_id
                    file_show_id = data.get("show_id")
                    season_id_data = data.get("season_id")

                    # Determine if this is a show cover or season cover
                    if season_id_data:
                        # This is a season cover
                        self.callbacks.debug(f"Season cover: {season_id_data}", "MediuxScraper/_process_set")
                        # Try to get season number from seasons array if available
                        if seasons:
                            season_id = season_id_data.get("id")
                            if season_id:
                                season_data = [s for s in seasons if s["id"] == season_id]
                                if season_data:
                                    season = season_data[0]["season_number"]
                                else:
                                    season = season_id_data.get("season_number", 0)
                            else:
                                season = season_id_data.get("season_number", 0)
                        else:
                            # No seasons array, get directly from season_id
                            season = season_id_data.get("season_number", 0)
                        episode = "Cover"
                        file_type = "season_cover"
                    elif file_show_id is not None:
                        # This is a show cover
                        self.callbacks.debug(f"Show cover detected", "MediuxScraper/_process_set")
                        season = "Cover"
                        episode = None
                        file_type = "show_cover"
                    else:
                        self.callbacks.debug(f"⏩ Skipping poster - missing show_id and season_id", "MediuxScraper/_process_set")
                        self.callbacks.log(f"⚠️ {self.title} • {self.author} | Skipping poster (missing necessary metadata from MediUX)")
                        self.errored += 1
                        continue

                else:
                    # Unknown file type or structure, skip
                    self.callbacks.debug(f"⏩ Skipping unknown TV show file type: {data.get('fileType')}", "MediuxScraper/_process_set")
                    self.callbacks.log(f"⚠️ {self.title} • {self.author} | Skipping asset (unknown TV show file tye)")
                    self.errored += 1
                    continue

            elif media_type == MediaType.MOVIE.value:

                if data["movie_id"]:
                    movie_id = data["movie_id"]["id"]
                    if set_data.get("movie"):
                        # This is a movie poster
                        title = set_data["movie"]["title"]
                        year = int(set_data["movie"]["release_date"][:4])
                        file_type = "movie_poster"
                    elif set_data.get("collection"):
                        # This is a movie poster inside a collection set
                        movies = set_data["collection"]["movies"]
                        movie_data = [movie for movie in movies if movie["id"] == movie_id][0]
                        title = movie_data["title"]
                        year = int(movie_data["release_date"][:4])
                        file_type = "movie_poster"
                elif data["collection_id"]:
                    # This is a collection poster
                    title = set_data["collection"]["collection_name"]
                    file_type = "collection_poster"
                else:
                    if data["fileType"] == "movie_poster":
                        # This is a collection poster
                        file_type = "collection_poster"
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
                # Apply filters and exclusions
                if (self.options.has_no_filters() and file_type in self.config.mediux_filters) or self.options.has_filter(file_type):
                    if not self.options.is_excluded(image_stub, season if isinstance(season, int) else None, episode if isinstance(episode, int) else None):
                        self.callbacks.debug(
                            f"{i+1}. ✅ Including {file_type.replace('_', ' ')} for '{show_name} ({year})'"
                            + (f", Season {season}" if isinstance(season, int) else "")
                            + (f", Episode {episode}" if isinstance(episode, int) else "")
                            + ".", "MediuxScraper/_process_set"
                        )
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
                        self.tv_artwork.append(tv_artwork)
                    else:
                        self.exclusions += 1
                        self.callbacks.debug(
                            f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{show_name} ({year})'"
                            + (f", Season {season}" if isinstance(season, int) else "")
                            + (f", Episode {episode}" if isinstance(episode, int) else "")
                            + " based on exclusions.", "MediuxScraper/_process_set"
                        )
                else:
                    self.filtered += 1
                    self.callbacks.debug(
                        f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{show_name} ({year})'"
                        + (f", Season {season}" if isinstance(season, int) else "")
                        + (f", Episode {episode}" if isinstance(episode, int) else "")
                        + " based on filters.", "MediuxScraper/_process_set"
                    )

            elif media_type == MediaType.MOVIE.value:
                if "Collection" in title:
                    if (self.options.has_no_filters() and file_type in self.config.mediux_filters) or self.options.has_filter(file_type):
                        if not self.options.is_excluded(image_stub):
                            self.callbacks.debug(f"{i+1}. ✅ Including {file_type.replace('_', ' ')} for '{title}'.", "MediuxScraper/_process_set")
                            collection_artwork = {}
                            collection_artwork["title"] = title
                            collection_artwork["url"] = poster_url
                            collection_artwork["id"] = image_stub
                            collection_artwork["source"] = ScraperSource.MEDIUX.value
                            collection_artwork["type"] = file_type
                            collection_artwork["year"] = None
                            collection_artwork["author"] = self.author
                            self.collection_artwork.append(collection_artwork)
                        else:
                            self.exclusions += 1
                            self.callbacks.debug(f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{title}' based on exclusions.", "MediuxScraper/_process_set")
                    else:
                        self.filtered += 1
                        self.callbacks.debug(f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{title}' based on filters.", "MediuxScraper/_process_set")
                else:
                    if (self.options.has_no_filters() and file_type in self.config.mediux_filters) or self.options.has_filter(file_type):
                        if not self.options.is_excluded(image_stub):
                            self.callbacks.debug(f"{i+1}. ✅ Including {file_type.replace('_', ' ')} for '{title} ({year})'.", "MediuxScraper/_process_set")
                            movie_artwork = {}
                            movie_artwork["title"] = title
                            movie_artwork["year"] = int(year)
                            movie_artwork["url"] = poster_url
                            movie_artwork["source"] = ScraperSource.MEDIUX.value
                            movie_artwork["id"] = image_stub
                            movie_artwork["type"] = file_type
                            movie_artwork["author"] = self.author
                            movie_artwork["tmdb_id"] = movie_id
                            self.movie_artwork.append(movie_artwork)
                        else:
                            self.exclusions += 1
                            self.callbacks.debug(f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{title} ({year})' based on exclusions.", "MediuxScraper/_process_set")
                    else:
                        self.filtered += 1
                        self.callbacks.debug(f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{title} ({year})' based on filters.", "MediuxScraper/_process_set")