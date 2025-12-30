from typing import Optional
from urllib.parse import urlparse

from core.constants import TPDB_BASE_URL, MEDIUX_BASE_URL, SOURCE_THEPOSTERDB, SOURCE_MEDIUX
from core.exceptions import ScraperException
from models.artwork_types import MovieArtworkList, TVArtworkList, CollectionArtworkList
from models.options import Options
from scrapers.mediux_scraper import MediuxScraper
from scrapers.theposterdb_scraper import ThePosterDBScraper
from utils.notifications import debug_me


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

    def __init__(self, url: str) -> None:
        self.url: str = url
        self.options: Options = Options()
        self.movie_artwork: MovieArtworkList = []
        self.tv_artwork: TVArtworkList = []
        self.collection_artwork: CollectionArtworkList = []
        self.source: Optional[str] = None
        self.title: Optional[str] = None
        self.author: Optional[str] = None
        self.exclusions: int = 0

        # Set source based on the contents of the URL
        parsed_url = urlparse(url)
        host = parsed_url.hostname
        if host == urlparse(TPDB_BASE_URL).hostname:
            self.source = SOURCE_THEPOSTERDB
        elif host == urlparse(MEDIUX_BASE_URL).hostname and ("/sets/" in url or "/boxsets/" in url):
            self.source = SOURCE_MEDIUX
        elif ".html" in url:
            self.source = "html"

    # Set options - otherwise will use defaults of False
    def set_options(self, options: Options) -> None:
        self.options = options

    def scrape(self) -> None:

        """
        Runs the correct scraper based on the source of the URL (as set in the __init__ function)

        Returns:
            None
        """
        try:
            debug_me(f"Scraping from {self.source}", "Scraper/scrape")
            if self.source == SOURCE_THEPOSTERDB:
                self.scrape_theposterdb()
            elif self.source == SOURCE_MEDIUX:
                self.scrape_mediux()
            elif self.source == "html":
                return self.scrape_html()
            else:
                raise ScraperException(f"Invalid source provided ({self.source if self.source else 'empty source'})")
        except Exception:
            raise

    def scrape_theposterdb(self) -> None:
        try:
            theposterdb_scraper = ThePosterDBScraper(self.url)
            theposterdb_scraper.set_options(self.options)
            self.exclusions = theposterdb_scraper.scrape()

            self.title = theposterdb_scraper.title
            self.author = theposterdb_scraper.author
            self.movie_artwork = theposterdb_scraper.movie_artwork
            self.tv_artwork = theposterdb_scraper.tv_artwork
            self.collection_artwork = theposterdb_scraper.collection_artwork

        except ScraperException:
            raise
        except Exception as e:
            raise Exception(f"Unexpected error: {e}")

    def scrape_mediux(self) -> None:

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
            self.exclusions = mediux_scraper.scrape()

            self.title = mediux_scraper.title
            self.author = mediux_scraper.author
            self.movie_artwork = mediux_scraper.movie_artwork
            self.tv_artwork = mediux_scraper.tv_artwork
            self.collection_artwork = mediux_scraper.collection_artwork

        except ScraperException:
            raise
        except Exception as e:
            raise Exception(f"Unexpected error: {e}")

    def scrape_html(self) -> None:

        """
        Scrapes a local HTML file.  Not sure what this option is actually used for!

        I'm guessing it was a saved page used so that TPDb wasn't hammered during
        development, but we'll keep it for posterity

        Returns:
            None
        """

        self.scrape_theposterdb()
