from typing import Optional, Any
from core import globals
from pprint import pprint

from utils import soup_utils
from utils import utils
from utils.notifications import debug_me
from models.options import Options
from core.exceptions import ScraperException
from core.enums import MediaType, ScraperSource, FileType
from core.constants import MEDIUX_API_BASE_URL, MEDIUX_QUALITY_SUFFIX
from models.artwork_types import MovieArtworkList, TVArtworkList, CollectionArtworkList

class MediuxScraper:

    def __init__(self, url: str) -> None:
        self.soup: Optional[Any] = None
        self.url: str = url
        self.title: Optional[str] = None
        self.options: Options = Options()

        self.movie_artwork: MovieArtworkList = []
        self.tv_artwork: TVArtworkList = []
        self.collection_artwork: CollectionArtworkList = []


    # Set options - otherwise will use defaults of False
    def set_options(self, options: Options) -> None:
        self.options = options


    def scrape(self) -> None:

        self.soup = soup_utils.cook_soup(self.url)

        base_url = MEDIUX_API_BASE_URL
        quality_suffix = MEDIUX_QUALITY_SUFFIX
        scripts = self.soup.find_all('script')
        media_type = None

        year = 0  # Default year value
        title = "Untitled"  # Default title value

        try:
            for script in scripts:
                if 'files' in script.text:
                    if 'set' in script.text:
                        if 'Set Link\\' not in script.text:
                            data_dict = utils.parse_string_to_dict(script.text)

                            if data_dict["set"]["show"] is not None:
                                self.title = data_dict["set"]["show"]["name"]
                            elif data_dict["set"]["movie"] is not None:
                                self.title = data_dict["set"]["movie"]["title"]
                            elif data_dict["set"]["collection"] is not None:
                                self.title = data_dict["set"]["collection"]["collection_name"]

                            poster_data = data_dict["set"]["files"]

            for data in poster_data:
                if data["show_id"] is not None or data["show_id_backdrop"] is not None or data["episode_id"] is not None or \
                        data["season_id"] is not None or data["show_id"] is not None:
                    media_type = MediaType.TV_SHOW.value
                else:
                    media_type = MediaType.MOVIE.value

            for data in poster_data:
                debug_me(str(data["id"]),"MediuxScraper/scrape")

                if media_type == MediaType.TV_SHOW.value:

                    episodes = data_dict["set"]["show"]["seasons"]
                    show_name = data_dict["set"]["show"]["name"]

                    try:
                        year = int(data_dict["set"]["show"]["first_air_date"][:4])
                    except (KeyError, ValueError, TypeError):
                        year = None

                    if data["fileType"] == FileType.TITLE_CARD.value:
                        episode_id = data["episode_id"]["id"]
                        season = data["episode_id"]["season_id"]["season_number"]
                        title = data["title"]
                        try:
                            episode = int(title.rsplit(" E", 1)[1])
                        except (IndexError, ValueError):
                            debug_me(f"Error getting episode number for {title}.", "MediuxScraper/scrape")

                        file_type = FileType.TITLE_CARD.value

                    elif data["fileType"] == FileType.BACKDROP.value and data["show_id_backdrop"] is not None:
                        debug_me(f"Backdrop: {data['show_id_backdrop']}", "MediuxScraper/scrape")
                        season = "Backdrop"
                        episode = None
                        file_type = "background"

                    elif data["fileType"] == FileType.POSTER.value and data["season_id"] is None:
                        debug_me(f"Cover: {data['show_id']}", "MediuxScraper/scrape")
                        season = "Cover"
                        episode = None
                        file_type = "show_cover"

                    elif data["fileType"] == FileType.POSTER.value and data["season_id"] is not None:
                        debug_me(f"Season cover: {data['season_id']}", "MediuxScraper/scrape")
                        season_id = data["season_id"]["id"]
                        season_data = [episode for episode in episodes if episode["id"] == season_id][0]
                        episode = "Cover"
                        season = season_data["season_number"]
                        file_type = "season_cover"

                elif media_type == MediaType.MOVIE.value:

                    if data["movie_id"]:
                        if data_dict["set"]["movie"]:
                            # This is a movie poster
                            title = data_dict["set"]["movie"]["title"]
                            year = int(data_dict["set"]["movie"]["release_date"][:4])
                            file_type = "poster"
                        elif data_dict["set"]["collection"]:
                            # This is a movie poster inside a collection set
                            movie_id = data["movie_id"]["id"]
                            movies = data_dict["set"]["collection"]["movies"]
                            movie_data = [movie for movie in movies if movie["id"] == movie_id][0]
                            title = movie_data["title"]
                            year = int(movie_data["release_date"][:4])
                            file_type = "poster"
                    elif data["collection_id"]:
                        # This is a collection poster
                        title = data_dict["set"]["collection"]["collection_name"]
                        file_type = "collection poster"
                    else:
                        if data["fileType"] == "poster":
                            # This is a collection poster
                            file_type = "collection poster"
                            title = data_dict["set"]["collection"]["collection_name"]
                        elif data["fileType"] == "backdrop":
                            # This is a movie background
                            if data["movie_id_backdrop"]:
                                movie_id = data["movie_id_backdrop"]["id"]
                                if data_dict["set"]["collection"] is not None:
                                    movies = data_dict["set"]["collection"]["movies"]
                                    movie_data = [movie for movie in movies if movie["id"] == movie_id][0]
                                else:
                                    movie_data = data_dict["set"]["movie"]
                                title = movie_data["title"]
                                year = int(movie_data["release_date"][:4])
                                file_type = "background"
                            else:
                                # The only remaining artwork can be the collection background
                                title = data_dict["set"]["collection"]["collection_name"]
                                file_type = "background"        

                image_stub = data["id"]
                poster_url = f"{base_url}{image_stub}{quality_suffix}"

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

                    debug_me(f"TV Artwork: {tv_artwork}", "MediuxScraper/scrape")
                    self.tv_artwork.append(tv_artwork)

                elif media_type == MediaType.MOVIE.value:
                    if "Collection" in title:
                        collection_artwork = {}
                        collection_artwork["title"] = title
                        collection_artwork["url"] = poster_url
                        collection_artwork["id"] = image_stub
                        collection_artwork["source"] = ScraperSource.MEDIUX.value
                        collection_artwork["type"] = file_type # Added by me
                        collection_artwork["year"] = None
                        debug_me(f"Collection Artwork: {collection_artwork}", "MediuxScraper/scrape")
                        self.collection_artwork.append(collection_artwork)
                    else:
                        movie_artwork = {}
                        movie_artwork["title"] = title
                        movie_artwork["year"] = int(year)
                        movie_artwork["url"] = poster_url
                        movie_artwork["source"] = ScraperSource.MEDIUX.value
                        movie_artwork["id"] = image_stub
                        movie_artwork["type"] = file_type # Added by me
                        debug_me(f"Movie Artwork: {movie_artwork}", "MediuxScraper/scrape")
                        self.movie_artwork.append(movie_artwork)

            if globals.debug:
                if self.collection_artwork:
                    debug_me(f"Found {len(self.collection_artwork)} collection asset(s) for {len({item["title"] for item in self.collection_artwork})} collection(s):", "MediuxScraper/scrape")
                    print(f"\033[1m\033[32m*************************************************************")
                    pprint(self.collection_artwork)
                    print("*************************************************************\033[0m")  
                if self.movie_artwork:
                    debug_me(f"Found {len(self.movie_artwork)} movie asset(s) for {len({item["title"] for item in self.movie_artwork})} movie(s):","MediuxScraper/scrape")
                    print(f"\033[1m\033[32m*************************************************************")
                    pprint(self.movie_artwork)
                    print(f"*************************************************************\033[0m")
                if self.tv_artwork:
                    debug_me(f"Found {len(self.tv_artwork)} TV show asset(s) for {len({item["title"] for item in self.tv_artwork})} TV show(s):", "MediuxScraper/scrape")
                    print(f"\033[1m\033[32m*************************************************************")
                    pprint(self.tv_artwork)
                    print("*************************************************************\033[0m")

        except ScraperException:
            raise
        except Exception as e:
            raise ScraperException(f"Can't scrape from MediUX: {str(e)}") from e