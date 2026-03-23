import math
from typing import Optional, Any

from processors import media_metadata
from utils import soup_utils
import time
from models.options import Options
from models.callbacks import ProcessingCallbacks
from core.exceptions import ScraperException
from core.config import Config
from core.enums import MediaType, ScraperSource
from core.constants import TPDB_API_ASSETS_URL, TPDB_USER_UPLOADS_PER_PAGE, BOOTSTRAP_COLORS, ANSI_RESET, ANSI_BOLD
from models.artwork_types import MovieArtworkList, TVArtworkList, CollectionArtworkList


class ThePosterDBScraper:

    def __init__(self, url: str, callbacks: Optional[ProcessingCallbacks]) -> None:
        self.soup: Optional[Any] = None
        self.url: str = url
        self.title: Optional[str] = None
        self.options: Options = Options()
        self.config: Config = Config()
        self.callbacks: Optional[ProcessingCallbacks] = callbacks
        self.config.load()
        self.author: Optional[str] = None
        self.tmdb_id: Optional[int] = None
        self.skipped: int = 0
        self.exclusions: int = 0
        self.filtered: int = 0
        self.errored: int = 0
        self.total: int = 0
        self.is_child: bool = False

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

            if "/user/" in self.url and not self.is_child:
                self.soup = soup_utils.cook_soup(self.url)
                self.callbacks.debug(f"★ Got a valid user URL {self.url}", "ThePosterDBScraper/scrape")
                self.callbacks.debug(f"★ Processing user URL with options {self.options}", "ThePosterDBScraper/scrape")

                # Get the user information, don't bother with set title because it's a user page
                self.get_set_author(self.soup)

                # Find out how many total assets and pages there are for this user
                self.scrape_user_info()
                self.callbacks.log(f"🔄 TPDb user • {self.author} | Processing {self.user_pages} asset pages with {self.user_uploads} assets")
                self.callbacks.debug(f"There are {self.user_uploads} assets and {self.user_pages} pages for user {self.author}", "ThePosterDBScraper/scrape")
                self.callbacks.progress(0, 0, f"Collecting assets from TPDb user {self.author}")

                collected = 0
                for user_page in range(self.user_pages):
                    self.callbacks.progress(user_page + 1, self.user_pages, f"Collecting assets from TPDb user {self.author} • {user_page + 1} of {self.user_pages} pages • {collected} assets collected of {self.user_uploads}")
                    #self.callbacks.status(f"Scraping TPDb asset pages for user {self.author}", color="info", sticky=True, spinner=True)
                    self.scrape_user_page(user_page)
                    movies = len(self.movie_artwork)
                    collections = len(self.collection_artwork)
                    shows = len(self.tv_artwork)
                    collected = movies + shows + collections
                    self.callbacks.debug(f"Processed {user_page + 1} out of {self.user_pages} user pages. Collected {movies} movie, {collections} collection and {shows} TV show assets so far, skipped {self.skipped}", "ThePosterDBScraper/scrape")
                self.callbacks.debug(f"---------> Total assets collected: {collected} of {self.user_uploads}", "ThePosterDBScraper/scrape")

                return

            if "/poster/" in self.url:
                self.callbacks.debug(f"★ Got a poster URL {self.url}, looking up the correct set URL...", "ThePosterDBScraper/scrape")
                poster_soup = soup_utils.cook_soup(self.url)
                self.url = poster_soup.find('a', title='View Set Page')['href']

            if self.url and ("/set/" in self.url or "/user/" in self.url):
                self.soup = soup_utils.cook_soup(self.url)
                if not self.is_child:
                    self.callbacks.debug(f"★ Got a valid URL {self.url}", "ThePosterDBScraper/scrape")
                    self.callbacks.debug(f"★ Processing URL with options {self.options}", "ThePosterDBScraper/scrape")

                if "/user/" not in self.url: # Only get the title if it's not a user URL
                    self.get_set_title(self.soup)
                self.get_set_author(self.soup)

                # Get the standard set of posters on the TPDb page
                self.scrape_posters(self.soup)

                # Get the additional posters if required
                if self.options.add_posters:
                    self.scrape_additional_posters()

                # Get the additional sets if required
                if self.options.add_sets:
                    self.scrape_additional_sets()

                self.skipped = self.exclusions + self.filtered + self.errored

                self.total = len(self.movie_artwork) + len(self.tv_artwork) + len(self.collection_artwork) + self.skipped

                if self.errored > 0:
                    self.callbacks.debug(f"⚠️ Encountered errors scraping {self.errored} artwork items from {self.url}", "ThePosterDBScraper/scrape")
                if self.skipped > 0:
                    self.callbacks.debug(f"⏩ Skipped {self.skipped} assets(s) out of {self.total} based on exclusions ({self.exclusions}), filters ({self.filtered}) or errors ({self.errored}).", "ThePosterDBScraper/scrape")
                if self.collection_artwork:
                    self.callbacks.debug(f"✅ Included {len(self.collection_artwork)} collection asset(s) for {len({item['title'] for item in self.collection_artwork})} collection(s):", "ThePosterDBScraper/scrape")
                    self.callbacks.debug(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('info').get('ansi')}*************************************************************{ANSI_RESET}")
                    self.callbacks.debug(self.collection_artwork)
                    self.callbacks.debug(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('info').get('ansi')}*************************************************************{ANSI_RESET}")  
                if self.movie_artwork:
                    self.callbacks.debug(f"✅ Included {len(self.movie_artwork)} movie asset(s) for {len({item['title'] for item in self.movie_artwork})} movie(s):","ThePosterDBScraper/scrape")
                    self.callbacks.debug(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('info').get('ansi')}*************************************************************{ANSI_RESET}")
                    self.callbacks.debug(self.movie_artwork)
                    self.callbacks.debug(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('info').get('ansi')}*************************************************************{ANSI_RESET}")
                if self.tv_artwork:
                    self.callbacks.debug(f"✅ Included {len(self.tv_artwork)} TV show asset(s) for {len({item['title'] for item in self.tv_artwork})} TV show(s):", "ThePosterDBScraper/scrape")
                    self.callbacks.debug(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('info').get('ansi')}*************************************************************{ANSI_RESET}")
                    self.callbacks.debug(self.tv_artwork)
                    self.callbacks.debug(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('info').get('ansi')}*************************************************************{ANSI_RESET}")

                return

            else:
                raise ScraperException(f"Invalid or unsupported URL for ThePosterDB: {self.url}")
        except ScraperException:
            raise
        except Exception as e:
            self.callbacks.debug(f"Error processing URL {self.url} from ThePosterDB: {str(e)}", "ThePosterDBScraper/scrape")
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

    def scrape_user_page (self, page) -> None:
        
        try:
            page_url = f"{self.url}?section=uploads&page={page + 1}"
            child_scraper = ThePosterDBScraper(page_url, self.callbacks)
            child_scraper.set_options(self.options)
            child_scraper.is_child = True
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
            self.callbacks.debug(f"Failed to scrape user asset page {page}: {str(e)}", "ThePosterDBScraper/scrape_user_page")

    def get_set_title(self, soup: Any) -> None:
        try:
            self.title = soup.find('p', id = "set-title").a.string
        except (AttributeError, TypeError) as e:
            self.callbacks.debug(f"Set title lookup failed!", "ThePosterDBScraper/get_set_title")
        if self.title:
            self.callbacks.debug(f"Found set title: {self.title}", "ThePosterDBScraper/get_set_title")

    def get_set_author(self, soup: Any) -> None:
        """ 
        Finds the set author by inspecting the HTML source of a set or user page
        """
        if "/set/" in self.url:
            try:
                #self.author = soup.select_one('p#set-title span.font-italic a').string.strip()
                self.author = soup.find('p', class_='uploaded-by text-white d-inline-block text-truncate w-100').a.string
                self.callbacks.debug(f"Found set author: {self.author}", "ThePosterDBScraper/get_set_author")
            except:
                self.callbacks.debug(f"Set author lookup failed {soup}", "ThePosterDBScraper/get_set_author")
        elif "/user/" in self.url:
            try:
                self.author = soup.find('p', class_='h1 mb-0 mr-md-1').a.string
                self.callbacks.debug(f"Found author: {self.author}", "ThePosterDBScraper/get_set_author")
            except:
                self.callbacks.debug(f"Author lookup failed {soup}", "ThePosterDBScraper/get_set_author")

    def get_posters(self, poster_div: Any) -> None:

        """
        Processes the given HTML section to extract poster information.

        Args:
            poster_div (bs4.element.Tag): The HTML element containing the posters.

        Returns:
            None
        """
        cache_buster = f"&_cb={int(time.time())}"

        posters = poster_div.find_all('div', class_='col-6 col-lg-2 p-1')

        if posters[-1].find('a', class_='rounded view_all'):
            posters.pop()

        for i, poster in enumerate(posters):

            media_type = poster.find('a', class_="text-white", attrs={'data-toggle': 'tooltip', 'data-placement': 'top'}).get('title')
            poster_id = poster.find('div', class_='overlay').get('data-poster-id')

            poster_url = f"{TPDB_API_ASSETS_URL}/{poster_id}{cache_buster}"
            title_p = poster.find('p', class_='p-0 mb-1 text-break').string

            if media_type == "Show": 
                title, season, year = media_metadata.parse_show(title_p)

                if season == "Cover":
                    file_type = "show_cover"
                else:
                    file_type = "season_cover"
                    
                if (self.options.has_no_filters() and file_type in self.config.tpdb_filters) or self.options.has_filter(file_type):
                    if not self.options.is_excluded(poster_id, season if isinstance(season, int) else None, None):
                        self.callbacks.debug(
                            f"{i+1}. ✅ Including {file_type.replace('_', ' ')} for '{title} ({year})'"
                            + (f", Season {season}." if isinstance(season, int) else "."), "ThePosterDBScraper/get_posters"
                        )
                        show_artwork = {
                            "title": title,
                            "author": self.author,
                            "tmdb_id": self.tmdb_id,
                            "url": poster_url,
                            "season": season,
                            "episode": None,
                            "year": year,
                            "source": ScraperSource.THEPOSTERDB.value,
                            "id":poster_id,
                            "type": file_type
                        }
                        self.tv_artwork.append(show_artwork)
                    else:
                        self.exclusions += 1
                        self.callbacks.debug(
                            f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{title} ({year})'"
                            + (f", Season {season}." if isinstance(season, int) else "")
                            + f" based on exclusions.", "ThePosterDBScraper/get_posters"
                        )
                else:
                    self.filtered += 1
                    self.callbacks.debug(
                        f"{i+1}. ⏩ Skipping {file_type.replace('_', ' ')} for '{title} ({year})'"
                        + (f", Season {season}." if isinstance(season, int) else "")
                        + f" based on filters.", "ThePosterDBScraper/get_posters"
                    )
            elif media_type == MediaType.MOVIE.value:
                title, year = media_metadata.parse_movie(title_p)
                if (self.options.has_no_filters() and "movie_poster" in self.config.tpdb_filters) or self.options.has_filter("movie_poster"):
                    if not self.options.is_excluded(poster_id):
                        self.callbacks.debug(f"{i+1}. ✅ Including movie poster for '{title} ({year})'.", "ThePosterDBScraper/get_posters")
                        movie_artwork = {
                            "title": title,
                            "author": self.author,
                            "tmdb_id": self.tmdb_id,
                            "url": poster_url,
                            "year": year,
                            "source": ScraperSource.THEPOSTERDB.value,
                            "id":poster_id,
                            "type": "movie_poster"
                        }
                        self.movie_artwork.append(movie_artwork)
                    else:
                        self.exclusions += 1
                        self.callbacks.debug(f"{i+1}. ⏩ Skipping movie poster for '{title} ({year})' based on exclusions.", "ThePosterDBScraper/get_posters")
                else:
                    self.filtered += 1
                    self.callbacks.debug(f"{i+1}. ⏩ Skipping movie poster for '{title} ({year})' based on filters.", "ThePosterDBScraper/get_posters")
            elif media_type == MediaType.COLLECTION.value:
                if (self.options.has_no_filters() and "collection_poster" in self.config.tpdb_filters) or self.options.has_filter("collection_poster"):
                    if not self.options.is_excluded(poster_id):
                        self.callbacks.debug(f"{i+1}. ✅ Including collection poster for '{title_p}'.", "ThePosterDBScraper/get_posters")
                        collection_artwork = {
                            "title": title_p,
                            "author": self.author,
                            "url": poster_url,
                            "source": ScraperSource.THEPOSTERDB.value,
                            "id":poster_id,
                            "type": "collection_poster"
                        }
                        self.collection_artwork.append(collection_artwork)
                    else:
                        self.exclusions += 1
                        self.callbacks.debug(f"{i+1}. ⏩ Skipping collection poster for '{title_p}' based on exclusions.", "ThePosterDBScraper/get_posters")
                else:
                    self.filtered += 1
                    self.callbacks.debug(f"{i+1}. ⏩ Skipping collection poster for '{title_p}' based on filters.", "ThePosterDBScraper/get_posters")
            else:
                self.errored += 1
                self.callbacks.debug(f"⏩ Skipping artwork item - unknown media type: {title_p} | {poster_url}", "ThePostedDBScraper/get_posters")
                self.callbacks.log(f"{f'⚠️ {self.title} • ' if self.title is not None else ''}{self.author} | Skipping asset (unknown media type): {title_p}")

    def scrape_additional_posters(self) -> None:

        """

        Returns:

        """
        self.callbacks.debug("Looking for additional posters...", "ThePosterDBScraper/scrape_additional_posters")
        poster_div = self.soup.find_all('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')[-1]
        mt4s = self.soup.find('main').find_all('div', class_='mt-4')

        if mt4s:
            additional_posters = mt4s[-1].find('p').find('span').getText()
            if additional_posters == "Additional Posters":
                self.get_posters(poster_div)


    def scrape_additional_sets(self) -> None:

        self.callbacks.debug("Looking for additional sets...", "ThePosterDBScraper/scrape_additional_sets")
        mt4s = self.soup.find('main').find_all('div', class_='mt-4')

        for mt4 in mt4s:
            additional_set = mt4.find('p').find('span').getText()
            if additional_set.startswith("Additional Set -"):
                self.callbacks.debug(f"+ {additional_set}")
                poster_div = mt4.find_all('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')[-1]
                set_url = poster_div.find('a', class_='rounded view_all')['href']
                if set_url:
                    some_more_soup = soup_utils.cook_soup(set_url)
                    self.scrape_posters(some_more_soup)



    def scrape_posters(self, soup: Any) -> None:
        poster_div = soup.find('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')
        return self.get_posters(poster_div)
