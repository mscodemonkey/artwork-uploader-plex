import math
import media_metadata
import soup_utils
from notifications import debug_me

from options import Options
from scraper_exceptions import ScraperException
from utils import get_artwork_type


class ThePosterDBScraper:

    def __init__(self, url):
        self.soup = None
        self.url = url
        self.title = None
        self.options = Options()

        self.movie_artwork = []
        self.tv_artwork = []
        self.collection_artwork = []

        self.user_uploads = 0
        self.user_pages = 0


    # Set options - otherwise will use defaults of False
    def set_options(self, options):
        self.options = options


    # Scrape The Poster DB
    def scrape(self):

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
        except:
            raise ScraperException(f"Could not process URL for ThePosterDB: {self.url}")

    def scrape_user_info(self):
        try:
            self.soup = soup_utils.cook_soup(self.url)
            span_tag = self.soup.find('span', class_='numCount')
            number_str = span_tag['data-count']
            self.user_uploads = int(number_str)
            self.user_pages = math.ceil(self.user_uploads / 24)
        except:
            raise ScraperException(f"Can't get user information, please check the URL you're using")

    def get_set_title(self, soup):
        try:
            self.title = soup.find('p', id = "set-title").a.string
        except:
            debug_me(f"title lookup failed {soup}")

    def get_posters(self, poster_div):

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

            poster_url = f"https://theposterdb.com/api/assets/{poster_id}"
            title_p = poster.find('p', class_='p-0 mb-1 text-break').string

            if media_type == "Show":
                title, season, year = media_metadata.parse_show(title_p)
                show_poster = {"title": title, "url": poster_url, "season": season, "episode": None, "year": year, "source": "theposterdb", "id":poster_id}
                get_artwork_type(show_poster)
                self.tv_artwork.append(show_poster)
            elif media_type == "Movie":
                title, year = media_metadata.parse_movie(title_p)
                self.movie_artwork.append({"title": title, "url": poster_url, "year": year, "source": "theposterdb", "id":poster_id})
            elif media_type == "Collection":
                self.collection_artwork.append({"title": title_p, "url": poster_url, "source": "theposterdb", "id":poster_id})


    def scrape_additional_posters(self):

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


    def scrape_additional_sets(self):

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



    def scrape_posters(self, soup):
        poster_div = soup.find('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')
        return self.get_posters(poster_div)
