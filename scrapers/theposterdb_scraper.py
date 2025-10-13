import math
from typing import Optional, Any

from processors import media_metadata
from utils import soup_utils
from utils.notifications import debug_me

from models.options import Options
from core.exceptions import ScraperException
from utils.utils import get_artwork_type
from core.enums import MediaType, ScraperSource
from core.constants import TPDB_API_ASSETS_URL, TPDB_USER_UPLOADS_PER_PAGE
from models.artwork_types import MovieArtworkList, TVArtworkList, CollectionArtworkList


class ThePosterDBScraper:

    def __init__(self, url: str) -> None:
        self.soup: Optional[Any] = None
        self.url: str = url
        self.title: Optional[str] = None
        self.options: Options = Options()

        self.movie_artwork: MovieArtworkList = []
        self.tv_artwork: TVArtworkList = []
        self.collection_artwork: CollectionArtworkList = []

        self.user_uploads: int = 0
        self.user_pages: int = 0


    # Set options - otherwise will use defaults of False
    def set_options(self, options: Options) -> None:
        self.options = options


    # Scrape The Poster DB
    def scrape(self) -> None:

        """
        If we were passed a poster link, it should have a link to its corresponding poster set.
        Even if it's just one poster, it still belongs to a poster set. So, let's find that link and retrieve its contents.
        Then, we will grab the main set of posters from the poster set URL, as well as any additional sets or posters required.

        Returns:
            bool: True if the posters were successfully grabbed, False otherwise.
        """
        try:
            if "/poster/" in self.url:
                debug_me(f"★ Got a poster URL {self.url}, looking up the correct set URL...")
                poster_soup = soup_utils.cook_soup(self.url)
                self.url = poster_soup.find('a', class_='rounded view_all')['href']

            if self.url and ("/set/" in self.url or "/user/" in self.url):
                debug_me(f"★ Got a valid URL {self.url}")
                self.soup = soup_utils.cook_soup(self.url)

                self.get_set_title(self.soup)

                # Get the standard set of posters on the TPDb page
                self.scrape_posters(self.soup)

                # Get the additional posters if required
                if self.options.add_posters:
                    self.scrape_additional_posters()

                # Get the additional sets if required
                if self.options.add_sets:
                    self.scrape_additional_sets()

            else:
                raise ScraperException(f"Invalid or unsupported URL for ThePosterDB: {self.url}")
        except ScraperException:
            raise
        except Exception as e:
            raise ScraperException(f"Could not process URL for ThePosterDB: {self.url}") from e

    def scrape_user_info(self) -> None:
        try:
            self.soup = soup_utils.cook_soup(self.url)
            span_tag = self.soup.find('span', class_='numCount')
            number_str = span_tag['data-count']
            self.user_uploads = int(number_str)
            self.user_pages = math.ceil(self.user_uploads / TPDB_USER_UPLOADS_PER_PAGE)
        except (AttributeError, KeyError, ValueError, TypeError) as e:
            raise ScraperException(f"Can't get user information, please check the URL you're using") from e

    def get_set_title(self, soup: Any) -> None:
        try:
            self.title = soup.find('p', id = "set-title").a.string
        except (AttributeError, TypeError) as e:
            debug_me(f"title lookup failed {soup}", "ThePosterDBScraper/get_set_title")

    def get_posters(self, poster_div: Any) -> None:

        """
        Processes the given HTML section to extract poster information.

        Args:
            poster_div (bs4.element.Tag): The HTML element containing the posters.

        Returns:
            None
        """

        posters = poster_div.find_all('div', class_='col-6 col-lg-2 p-1')

        if posters[-1].find('a', class_='rounded view_all'):
            posters.pop()

        for poster in posters:

            media_type = poster.find('a', class_="text-white", attrs={'data-toggle': 'tooltip', 'data-placement': 'top'})['title']
            poster_id = poster.find('div', class_='overlay').get('data-poster-id')

           # if not self.options.is_excluded(poster_id):

            poster_url = f"{TPDB_API_ASSETS_URL}/{poster_id}"
            title_p = poster.find('p', class_='p-0 mb-1 text-break').string

            if media_type == "Show":
                title, season, year = media_metadata.parse_show(title_p)
                show_poster = {"title": title, "url": poster_url, "season": season, "episode": None, "year": year, "source": ScraperSource.THEPOSTERDB.value, "id":poster_id}
                get_artwork_type(show_poster)
                self.tv_artwork.append(show_poster)
            elif media_type == MediaType.MOVIE.value:
                title, year = media_metadata.parse_movie(title_p)
                self.movie_artwork.append({"title": title, "url": poster_url, "year": year, "source": ScraperSource.THEPOSTERDB.value, "id":poster_id})
            elif media_type == MediaType.COLLECTION.value:
                self.collection_artwork.append({"title": title_p, "url": poster_url, "source": ScraperSource.THEPOSTERDB.value, "id":poster_id})


    def scrape_additional_posters(self) -> None:

        """

        Returns:

        """
        debug_me("⚲ Looking for additional posters...")
        poster_div = self.soup.find_all('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')[-1]
        mt4s = self.soup.find('main').find_all('div', class_='mt-4')

        if mt4s:
            additional_posters = mt4s[-1].find('p').find('span').getText()
            if additional_posters == "Additional Posters":
                self.get_posters(poster_div)


    def scrape_additional_sets(self) -> None:

        debug_me("⚲ Looking for additional sets...")
        mt4s = self.soup.find('main').find_all('div', class_='mt-4')

        for mt4 in mt4s:
            additional_set = mt4.find('p').find('span').getText()
            if additional_set.startswith("Additional Set -"):
                debug_me(f"+ {additional_set}")
                poster_div = mt4.find_all('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')[-1]
                set_url = poster_div.find('a', class_='rounded view_all')['href']
                if set_url:
                    some_more_soup = soup_utils.cook_soup(set_url)
                    self.scrape_posters(some_more_soup)



    def scrape_posters(self, soup: Any) -> None:
        poster_div = soup.find('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')
        return self.get_posters(poster_div)
