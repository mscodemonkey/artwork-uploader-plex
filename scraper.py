from bs4 import BeautifulSoup

import soup_utils
import tpdb
import mediux_scraper
from options import Options
from scraper_exceptions import ScraperException
from theposterdb_scraper import ThePosterDBScraper
from mediux_scraper import MediuxScraper

class Scraper:

    """
    A class to scrape one of the supported providers

    Attributes:
        url (str): The URL to scrape

    Methods:
        set_options():          A way to pass in the scrape options (either from the CLI, in a line of the bulk file, or in the GUI)
        scrape():               Decides which scraper to use
        scrape_theposterdb():   Scrapes The Poster DB (theposterdb.com)
        scrape_mediux():        Scrapes MediUX (mediux.pro)
        scrape_html():          Scrapes a local HTML file using the Poster DB scraper
    """

    def __init__(self, url):
        self.url = url
        self.options = Options()
        self.movie_artwork = []
        self.tv_artwork = []
        self.collection_artwork = []
        self.source = None

        # Set source based on the contents of the URL
        if "theposterdb.com" in url:
            self.source = "theposterdb"
        elif "mediux.pro" in url and "sets" in url:
            self.source = "mediux"
        elif ".html" in url:
            self.source = "html"


    # Set options - otherwise will use defaults of False
    def set_options(self, options):
        self.options = options


    def scrape(self):

        """
        Runs the correct scraper based on the source of the URL (as set in the __init__ function)

        Returns:
            None
        """

        if self.source == "theposterdb":
            self.scrape_theposterdb()
        elif self.source == "mediux":
            self.scrape_mediux()
        elif self.source == "html":
            return self.scrape_html()
        else:
            raise ScraperException(f"Invalid source provided ({self.source if self.source else 'empty source'})")


    def scrape_theposterdb(self):
        try:

            theposterdb_scraper = ThePosterDBScraper(self.url)
            theposterdb_scraper.set_options(self.options)
            theposterdb_scraper.scrape()

            self.movie_artwork = theposterdb_scraper.movie_artwork
            self.tv_artwork = theposterdb_scraper.tv_artwork
            self.collection_artwork = theposterdb_scraper.collection_artwork

        except ScraperException:
            raise
        except Exception as e:
            raise Exception(f"Unexpected error: {e}")


    def scrape_mediux(self):

        """
        Scrape mediux.pro - this could be anything from a backdrop, posters or episode cards

        Returns:
            list: movie_artwork
            list: tv_artwork
            list: collection_artwork
        """

        try:

            mediux_scraper = MediuxScraper(self.url)
            mediux_scraper.set_options(self.options)
            mediux_scraper.scrape()

            self.movie_artwork = mediux_scraper.movie_artwork
            self.tv_artwork = mediux_scraper.tv_artwork
            self.collection_artwork = mediux_scraper.collection_artwork

        except ScraperException:
            raise
        except Exception as e:
            raise Exception(f"Unexpected error: {e}")


    def scrape_html(self):

        """
        Scrapes a local HTML file.  Not sure what this option is actually used for!

        I'm guessing it was a saved page used so that TPDb wasn't hammered during
        development, but we'll keep it for posterity

        Returns:
            None
        """

        with open(self.url, 'r', encoding='utf-8') as file:
            html_content = file.read()
            soup = BeautifulSoup(html_content, 'html.parser')
        return tpdb.scrape_posters(soup)

