
import soup_utils
import utils
from notifications import debug_me
from options import Options
from scraper_exceptions import ScraperException


# Disclaimer : I don't have a clue how this scraper works

class MediuxScraper:

    def __init__(self, url):
        self.soup = None
        self.url = url
        self.title = None
        self.options = Options()

        self.movie_artwork = []
        self.tv_artwork = []
        self.collection_artwork = []


    # Set options - otherwise will use defaults of False
    def set_options(self, options):
        self.options = options


    def scrape(self):

        self.soup = soup_utils.cook_soup(self.url)

        base_url = "https://mediux.pro/_next/image?url=https%3A%2F%2Fapi.mediux.pro%2Fassets%2F"
        quality_suffix = "&w=3840&q=80"
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
                    media_type = "Show"
                else:
                    media_type = "Movie"

            for data in poster_data:
                if media_type == "Show":

                    episodes = data_dict["set"]["show"]["seasons"]
                    show_name = data_dict["set"]["show"]["name"]

                    try:
                        year = int(data_dict["set"]["show"]["first_air_date"][:4])
                    except:
                        year = None

                    if data["fileType"] == "title_card":
                        episode_id = data["episode_id"]["id"]
                        season = data["episode_id"]["season_id"]["season_number"]
                        title = data["title"]
                        try:
                            episode = int(title.rsplit(" E", 1)[1])
                        except:
                            debug_me(f"Error getting episode number for {title}.")

                        file_type = "title_card"

                    elif data["fileType"] == "backdrop":
                        season = "Backdrop"
                        episode = None
                        file_type = "background"

                    elif data["season_id"] is not None:
                        season_id = data["season_id"]["id"]
                        season_data = [episode for episode in episodes if episode["id"] == season_id][0]
                        episode = "Cover"
                        season = season_data["season_number"]
                        file_type = "season_cover"

                    elif data["show_id"] is not None:
                        season = "Cover"
                        episode = None
                        file_type = "show_cover"

                elif media_type == "Movie":

                    if data["movie_id"]:
                        if data_dict["set"]["movie"]:
                            title = data_dict["set"]["movie"]["title"]
                            year = int(data_dict["set"]["movie"]["release_date"][:4])
                        elif data_dict["set"]["collection"]:
                            movie_id = data["movie_id"]["id"]
                            movies = data_dict["set"]["collection"]["movies"]
                            movie_data = [movie for movie in movies if movie["id"] == movie_id][0]
                            title = movie_data["title"]
                            year = int(movie_data["release_date"][:4])
                    elif data["collection_id"]:
                        title = data_dict["set"]["collection"]["collection_name"]

                image_stub = data["id"]
                poster_url = f"{base_url}{image_stub}{quality_suffix}"

                if media_type == "Show":
                    tv_artwork = {}
                    tv_artwork["title"] = show_name
                    tv_artwork["season"] = season
                    tv_artwork["episode"] = episode
                    tv_artwork["url"] = poster_url
                    tv_artwork["source"] = "mediux"
                    tv_artwork["year"] = year
                    tv_artwork["id"] = image_stub
                    self.tv_artwork.append(tv_artwork)

                elif media_type == "Movie":
                    if "Collection" in title:
                        collection_artwork = {}
                        collection_artwork["title"] = title
                        collection_artwork["url"] = poster_url
                        collection_artwork["id"] = image_stub
                        collection_artwork["source"] = "mediux"
                        self.collection_artwork.append(collection_artwork)
                    else:
                        movie_artwork = {}
                        movie_artwork["title"] = title
                        movie_artwork["year"] = int(year)
                        movie_artwork["url"] = poster_url
                        movie_artwork["source"] = "mediux"
                        movie_artwork["id"] = image_stub
                        self.movie_artwork.append(movie_artwork)
        except:
            raise ScraperException("Can't scrape from MediUX")