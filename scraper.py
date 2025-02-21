from bs4 import BeautifulSoup

import soup_utils
import tpdb
import mediux
from options import Options

class Scraper:

    def __init__(self, url):
        self.url = url
        self.options = Options()
        self.movie_artwork = []
        self.tv_artwork = []
        self.collection_artwork = []

        # Set source based on the contents of the URL
        if "theposterdb.com" in url:
            self.source = "theposterdb"
        elif "mediux.pro" in url and "sets" in url:
            self.source = "mediux"
        elif ".html" in url:
            self.source = "html"
        else:
            self.source = None

    # Set options - otherwise will use defaults of False
    def set_options(self, options):
        self.options = options

    # Choose which scraper to use
    def scrape(self):
        if self.source == "theposterdb":
            try:
                return self.scrape_theposterdb()
            except:
                raise Exception("Poster set not found. Check the URL you are using.")
        elif self.source == "mediux":
            return self.scrape_mediux()
        elif self.source == "html":
            return self.scrape_html()
        else:
            raise Exception("Poster set not found. Check the URL you are using.")

    # Scrape The Poster DB
    def scrape_theposterdb(self):

        # If we were passed a poster link, it should have a link to its corresponding poster set.
        # Even if it's just one poster, it still has a poster set.  So let's find that link and get its contents.

        if "/poster/" in self.url:

            print(f"★ Got a poster URL {self.url}, looking up the correct set URL...")
            soup = soup_utils.cook_soup(self.url)
            self.url = tpdb.find_link_to_poster_set(soup)

        if self.url and ("/set/" in self.url or "/user/" in self.url):

            # print(f"* Scraping {self.url}")

            soup = soup_utils.cook_soup(self.url)

            # Get the standard set of posters on the TPDb page
            movies, shows, collections = tpdb.scrape_posters(soup)
            self.movie_artwork.extend(movies)
            self.tv_artwork.extend(shows)
            self.collection_artwork.extend(collections)

            # Get the additional posters if required
            if self.options.add_posters:
                movies, shows, collections = tpdb.scrape_additional_posters(soup)
                self.movie_artwork.extend(movies)
                self.tv_artwork.extend(shows)
                self.collection_artwork.extend(collections)

            # Get the additional sets if required
            if self.options.add_sets:
                movies, shows, collections = tpdb.scrape_additional_sets(soup)
                self.movie_artwork.extend(movies)
                self.tv_artwork.extend(shows)
                self.collection_artwork.extend(collections)

            return self.movie_artwork, self.tv_artwork, self.collection_artwork

    # Scrape mediux.pro - this could be anything from a backdrop, posters or episode cards
    def scrape_mediux(self):
        soup = soup_utils.cook_soup(self.url)
        self.movie_artwork, self.tv_artwork, self.collection_artwork = mediux.scrape_mediux(soup)
        return self.movie_artwork, self.tv_artwork, self.collection_artwork

    # Scrape a local HTML file
    # Not sure what this option is - I'm guessing it was a saved page used so that TPDb wasn't hammered during development, but we'll keep it for posterity
    def scrape_html(self):
        with open(self.url, 'r', encoding='utf-8') as file:
            html_content = file.read()
        soup = BeautifulSoup(html_content, 'html.parser')
        return tpdb.scrape_posters(soup)