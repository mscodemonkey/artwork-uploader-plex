import requests
from plexapi.server import PlexServer
import plexapi.exceptions
import xml.etree.ElementTree
from plex_connector_exception import PlexConnectorException, LibraryNotFound
from options import Options

class PlexConnector:

    def __init__(self, base_url = None, token = None):
        self.plex = None
        self.base_url = base_url
        self.token = token
        self.tv_libraries = []
        self.movie_libraries = []
        self.options = Options()

    def set_options(self, options):
        self.options = options

    def reconnect(self, updated_config):
        self.plex = None
        self.base_url = updated_config.base_url
        self.token = updated_config.token

        try:
            self.connect()
            self.set_tv_libraries(updated_config.tv_library)
            self.set_movie_libraries(updated_config.movie_library)
        except:
            raise

    def connect(self):
        if not self.plex:
            if not self.base_url or not self.token:
                raise PlexConnectorException("Invalid Plex token or base URL. Please provide valid values in config.json or via the GUI.")

            try:
                self.plex = PlexServer(self.base_url, self.token)  # Initialize the Plex server connection

            except requests.exceptions.RequestException as e:
                # Handle network-related errors (e.g., unable to reach the server)
                self.plex = None
                raise PlexConnectorException('Unable to connect to Plex server. Please check the "base_url" in config.json or provide one.', f"Unable to connect to Plex server: {str(e)}")

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


    def set_tv_libraries(self, tv_libraries):

        if not self.plex:
            self.connect()

        if isinstance(tv_libraries, str):
            tv_libraries = [tv_libraries]
        elif not isinstance(tv_libraries, list):
            raise PlexConnectorException("tv_libraries must be either a string or a list")

        for tv_library in tv_libraries:
            try:
                plex_tv = self.plex.library.section(tv_library)
                self.tv_libraries.append(plex_tv)
            except plexapi.exceptions.NotFound:
                raise LibraryNotFound(
                    f'TV library named "{tv_library}" not found. Please check the "tv_library" in config.json or provide one.',
                    f'TV library named "{tv_library}" not found.')

        return self.tv_libraries

    def set_movie_libraries(self, movie_libraries):

        if not self.plex:
            self.connect()

        if isinstance(movie_libraries, str):
            movie_libraries = [movie_libraries]
        elif not isinstance(movie_libraries, list):
            raise PlexConnectorException("movie_libraries must be either a string or a list")

        for movie_library in movie_libraries:
            try:
                plex_movies = self.plex.library.section(movie_library)
                self.movie_libraries.append(plex_movies)
            except plexapi.exceptions.NotFound:
                raise LibraryNotFound(
                    f'Movie library named "{movie_library}" not found. Please check the "movie_library" in config.json or provide one.',
                    f'Movie library named "{movie_library}" not found')

        return self.movie_libraries


    # Find a specific collection in the movies library
    def find_collection(self, collection_title):

        if not self.plex:
            self.connect()

        collections = []

        for movie_library in self.movie_libraries:
            try:
                plex_collections = movie_library.collections()
                for collection in plex_collections:
                    if collection.title == collection_title:
                        collections.append(collection)
            except:
                pass

        if collections:
            return collections

        return None

    # Find a specific movie or TV show in the given library
    def find_in_library(self, item_type, item_title, item_year = None):

        if not self.plex:
            self.connect()

        items = []
        libraries = self.tv_libraries if item_type == "tv" else self.movie_libraries
        for library in libraries:
            try:
                if item_year is not None:
                    library_item = library.get(item_title, year = item_year)
                else:
                    library_item = library.get(item_title)
                if library_item:
                    items.append(library_item)
            except:
                pass
        if items:
            return items
        return None
