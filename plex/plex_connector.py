from typing import Optional, List, Union
import socket
import requests
from plexapi.server import PlexServer
from plexapi.library import LibrarySection, MovieSection, ShowSection
from plexapi.video import Movie, Show
from plexapi.collection import Collection
import plexapi.exceptions
import xml.etree.ElementTree
from urllib.parse import urlparse

from core.exceptions import PlexConnectorException, LibraryNotFound
from models.options import Options
from utils.notifications import debug_me
from core.config import Config

class PlexConnector:

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None) -> None:
        self.plex: Optional[PlexServer] = None
        self.base_url: Optional[str] = base_url
        self.token: Optional[str] = token
        self.tv_libraries: List[ShowSection] = []
        self.movie_libraries: List[MovieSection] = []
        self.options: Options = Options()

    def set_options(self, options: Options) -> None:
        self.options = options

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

            # Quick connectivity check before attempting full connection
            try:
                parsed = urlparse(self.base_url)
                host = parsed.hostname or 'localhost'
                port = parsed.port or 32400

                # Try to connect with a short timeout using connect_ex (non-blocking check)
                test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_socket.settimeout(3)
                result = test_socket.connect_ex((host, port))
                test_socket.close()

                if result != 0:
                    raise PlexConnectorException(
                        f'Cannot reach Plex server at {self.base_url}. Please check that the server is running and the address is correct.',
                        f"Connection refused (error code: {result})")
            except PlexConnectorException:
                raise
            except (socket.timeout, socket.error, OSError) as e:
                raise PlexConnectorException(
                    f'Cannot reach Plex server at {self.base_url}. Connection timed out after 3 seconds.',
                    f"Connection failed: {str(e)}")

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
        debug_me(f"The following TV libraries have been set: {[library.title for library in self.tv_libraries]}", "PlexConnector/set_tv_libraries")
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
        debug_me(f"The following movie libraries have been set: {[library.title for library in self.movie_libraries]}", "PlexConnector/set_movie_libraries")
        return self.movie_libraries


    # Find a specific collection in the movies library
    def find_collection(self, collection_title: str) -> Optional[List[Collection]]:

        if not self.plex:
            self.connect()

        collections = []
        libs = []

        for movie_library in self.movie_libraries:
            try:
                plex_collections = movie_library.collections()
                for collection in plex_collections:
                    if collection.title == collection_title:
                        debug_me(f"Found '{collection_title}' in '{movie_library.title}'", "PlexConnector/find_collection")
                        collections.append(collection)
                        libs.append(movie_library.title)
            except Exception as e:
                # Continue checking other libraries if one fails
                debug_me(f"Error searching collection in library: {e}", "PlexConnector/find_collection")
                pass

        if collections:
            return collections, libs

        return None, None

    # Find a specific movie or TV show in the given library
    def find_in_library(self, item_type: str, item_title: str, item_year: Optional[int] = None) -> Optional[List[[Union[Movie, Show], str]]]:

        if not self.plex:
            self.connect()

        items = []
        libs = []
        libraries = self.tv_libraries if item_type == "tv" else self.movie_libraries
        for i, library in enumerate(libraries):
            try:
                if item_year is not None:
                    library_item = library.get(item_title, year = item_year)
                    library_name = library.title
                    debug_me(f"Found '{library_item.title} ({item_year})' in '{library_name}'", "PlexConnector/find_in_library")
                else:
                    library_item = library.get(item_title)
                    library_name = library.title
                if library_item:
                    items.append(library_item)
                    libs.append(library_name)
            except Exception as e:
                # Continue checking other libraries if one fails
                debug_me(f"Unable to find '{item_title} ({item_year})' in '{libraries[i].title}': {e}", "PlexConnector/find_in_library")
                pass
        if items:
            return items, libs
        return None, None
