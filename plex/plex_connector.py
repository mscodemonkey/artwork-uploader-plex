import requests, plexapi.exceptions, xml.etree.ElementTree, re
from typing import Optional, List, Tuple, Union, Literal
from core.enums import MediaType
from plexapi.server import PlexServer
from plexapi.library import MovieSection, ShowSection
from plexapi.video import Movie, Show
from plexapi.collection import Collection
from core.exceptions import PlexConnectorException, LibraryNotFound
from models.artwork_types import AnyArtwork
from models.options import Options
from utils.notifications import debug_me
from core.config import Config
from plex.library_index import PlexLibraryIndex, normalize_title

class PlexConnector:

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None) -> None:
        self.plex: Optional[PlexServer] = None
        self.base_url: Optional[str] = base_url
        self.token: Optional[str] = token
        self.tv_libraries: List[ShowSection] = []
        self.movie_libraries: List[MovieSection] = []
        self.options: Options = Options()
        self._index: PlexLibraryIndex = PlexLibraryIndex(self.movie_libraries, self.tv_libraries)

    def set_options(self, options: Options) -> None:
        self.options = options

    def _initialize_index(self):
        self._index._initialize_index(self.movie_libraries, self.tv_libraries)

    def reconnect(self, updated_config: Config) -> None:
        self.plex = None
        self.base_url = updated_config.base_url
        self.token = updated_config.token

        try:
            self.connect()
            self.set_tv_libraries(updated_config.tv_library)
            self.set_movie_libraries(updated_config.movie_library)
        except PlexConnectorException:
            raise
        except Exception:
            raise

    def connect(self) -> None:
        if not self.plex:
            if not self.base_url or not self.token:
                raise PlexConnectorException("Invalid Plex token or base URL. Please provide valid values in config.json or via the GUI.")

            try:
                self.plex = PlexServer(self.base_url, self.token, timeout=10)  # Initialize the Plex server connection with 10 second timeout

            except requests.exceptions.Timeout as e:
                # Handle timeout errors specifically
                self.plex = None
                raise PlexConnectorException(
                    f'Connection to Plex server at {self.base_url} timed out after 10 seconds. Please check that the server is running and accessible.',
                    f"Plex connection timeout: {str(e)}")

            except requests.exceptions.RequestException as e:
                # Handle network-related errors (e.g., unable to reach the server)
                self.plex = None
                raise PlexConnectorException(
                    f'Unable to connect to Plex server at {self.base_url}. Please check the "base_url" in config.json and ensure the server is accessible.',
                    f"Unable to connect to Plex server: {str(e)}")

            except plexapi.exceptions.Unauthorized as e:
                # Handle authentication-related errors (e.g., invalid token)
                self.plex = None
                raise PlexConnectorException(f'Invalid Plex token "{self.token}" -  please check the "token" in config.json or provide one.', f"Invalid Plex token: {str(e)}")

            except xml.etree.ElementTree.ParseError as e:
                # Handle XML parsing errors (e.g., invalid XML response from Plex)
                self.plex = None
                raise PlexConnectorException('Received invalid XML from Plex server. Check server connection.', f"Received invalid XML from Plex server: {str(e)}")

            except Exception as e:
                # Handle any other unexpected errors
                self.plex = None
                raise PlexConnectorException(f"Unexpected error: {str(e)}", f"Unexpected error: {str(e)}")


    def set_tv_libraries(self, tv_libraries: Union[str, List[str]]) -> List[ShowSection]:

        if not self.plex:
            self.connect()

        if isinstance(tv_libraries, str):
            tv_libraries = [tv_libraries]
        elif not isinstance(tv_libraries, list):
            raise PlexConnectorException("tv_libraries must be either a string or a list")

        self.tv_libraries = []
        for tv_library in tv_libraries:
            try:
                plex_tv = self.plex.library.section(tv_library)
                self.tv_libraries.append(plex_tv)
            except plexapi.exceptions.NotFound:
                raise LibraryNotFound(
                    f'TV library named "{tv_library}" not found. Please check the "tv_library" in config.json or provide one.',
                    f'TV library named "{tv_library}" not found.')
        debug_me(f"The following TV libraries have been set: {[library.title for library in self.tv_libraries]}")
        return self.tv_libraries

    def set_movie_libraries(self, movie_libraries: Union[str, List[str]]) -> List[MovieSection]:

        if not self.plex:
            self.connect()

        if isinstance(movie_libraries, str):
            movie_libraries = [movie_libraries]
        elif not isinstance(movie_libraries, list):
            raise PlexConnectorException("movie_libraries must be either a string or a list")

        self.movie_libraries = []
        for movie_library in movie_libraries:
            try:
                plex_movies = self.plex.library.section(movie_library)
                self.movie_libraries.append(plex_movies)
            except plexapi.exceptions.NotFound:
                raise LibraryNotFound(
                    f'Movie library named "{movie_library}" not found. Please check the "movie_library" in config.json or provide one.',
                    f'Movie library named "{movie_library}" not found')
        debug_me(f"The following movie libraries have been set: {[library.title for library in self.movie_libraries]}")
        return self.movie_libraries


    # Find a specific collection in the movies library
    def find_collection(self, collection_title: str, fuzzy: bool = False) -> Optional[List[Collection]]:

        if not self.plex:
            self.connect()

        collections = []
        libraries = []

        for library in self.movie_libraries + self.tv_libraries:
            try:
                plex_collections = library.collections()
                for collection in plex_collections:
                    # Removes "Collection" from the title (if present) and anything between parenthesis, 
                    # like 'Alfred Hitchcock (Directing)' or 'Tom Cruise (Acting)'
                    fuzzy_match_str = re.sub(r"\s*\(.*?\)", "", collection_title.replace(" Collection", "")).strip()
                    exact_match = collection_title.lower() == collection.title.lower()
                    fuzzy_match = fuzzy and collection.title.lower().startswith(fuzzy_match_str.lower())

                    if exact_match or fuzzy_match:
                        if fuzzy:
                            debug_me(f"Fuzzy-matched '{collection_title}' to '{collection.title}' in '{library.title}'")
                        else:
                            debug_me(f"Found collection '{collection_title} in '{library.title}'")
                        collections.append(collection)
                        libraries.append(library.title)
            except Exception as e:
                # Continue checking other libraries if one fails
                debug_me(f"Error searching collection in library: {e}")
                raise PlexConnectorException(f"Error seraching Plex for {collection_title}")

        if collections:
            return collections, libraries

        debug_me(f"Collection '{collection_title}' not found in Plex")
        return None, None

    # Find a specific movie or TV show in the given library
    def find_in_library(self, media_type: Literal[MediaType.MOVIE, MediaType.TV_SHOW], artwork: AnyArtwork) -> Tuple[Optional[List[Union[Movie, Show]]], Optional[List[str]]]:
        """
        Finds a specific movie or TV show in the appropriate library based on the provided artwork information.

        Args:
            item_type: The type of item to search for ("movie" or "tv").
            artwork: The artwork information containing title and year.

        Returns:
            A tuple containing:
            - A list of found Movie or Show objects, or None if not found.
            - A list of library names where the items were found, or None if not found.
        """
        if not self.plex:
            self.connect()

        items = []
        lib_names = []

        libraries = self.tv_libraries if media_type == MediaType.TV_SHOW else self.movie_libraries
        for library in libraries:
            library_item = None
            try:
                library_item = library.getGuid(f"tmdb://{artwork.get('tmdb_id')}")
                library_name = library.title
                debug_me(f"Found '{artwork.get('title')} ({artwork.get('year')})' with TMDb ID '{artwork.get('tmdb_id')}' as '{library_item.title} ({library_item.year})' in '{library_name}'")

                if library_item:
                    items.append(library_item)
                    lib_names.append(library_name)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                debug_me(f"Plex server timed out while searching '{artwork.get('title')} ({artwork.get('year')})' in {library.title}")
                lib_names.append(f"ERROR:{library.title}")
                pass
            except Exception as e:
                # Continue checking other libraries if one fails
                debug_me(f"Unable to find '{artwork.get('title')} ({artwork.get('year')})' as TMDb ID '{artwork.get('tmdb_id')}' in '{library.title}': {e}")
                pass
        for lib_name in lib_names:
            if "ERROR" in lib_name:
                raise PlexConnectorException(f"Plex server timed out searching library {lib_name.split(":")[-1]}")
        if items:
            return items, lib_names
        return None, None
    
    def movie_or_show(self, title:str, year:Optional[int] = None) -> Tuple[Optional[str], Optional[int], Optional[str], Optional[int]]:
        """
        Looks up a title in the Plex libraries.

        Args:
            title: The title of the movie or TV show to look up.
            year: Optional year to narrow down the search.

        Returns:
            A tuple containing:
            - media_type (str | None): "Movie" or "TV Show" if found, else None
            - tmdb_id (int | None): The TMDb ID if found, else None
            - found_title (str | None): The exact title found in Plex, else None
            - found_year (int | None): The year of the title found in Plex, else None
        """

        if not self.plex:
            try:
                self.connect()
            except PlexConnectorException as e:
                debug_me(f"PlexConnectorException raised when connecting to Plex: {str(e)}")
                return "Error", None, None, None

        try:
            self._initialize_index()
        except Exception as e:
            debug_me(f"Error building Plex lookup index: {str(e)}")
            return "Error", None, None, None

        status, match = self._index.lookup(title, year)
        if status == "matched":
            media_type = match.get("type")
            tmdb_id = match.get("tmdb_id")
            found_title = match.get("title")
            found_year = match.get("year")
            library = match.get("library")
            if tmdb_id is not None:
                debug_me(f"Item '{title} ({year})' identified as '{found_title} ({found_year})' ({media_type}) in library '{library}' with TMDb ID {tmdb_id}")
            else:
                debug_me(f"Item '{title} ({year})' identified as '{found_title} ({found_year})' ({media_type}) in library '{library}', but TMDb ID not found")
            return media_type, tmdb_id, found_title, found_year

        debug_me(f"'{title} ({year})' not found in any library")
        return "unavailable", None, None, None