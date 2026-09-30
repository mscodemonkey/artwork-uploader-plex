"""find_in_library returns every item in a library that shares the film's guid, so a film kept as
more than one Plex edition gets artwork on each, the way a film in more than one library does.
plexapi's getGuid returns only the first of them.
"""

from types import SimpleNamespace

from plex.plex_connector import PlexConnector

GUID = "plex://movie/5d7768254de0ee001fcc83a5"


def _movie(rating_key, folder):
    part = SimpleNamespace(file=f"/data/movies/{folder}/{folder}.mkv")
    return SimpleNamespace(ratingKey=rating_key, title="Alien", year=1979, guid=GUID,
                           media=[SimpleNamespace(parts=[part])])


class _Section:
    """A movie library whose getGuid, like plexapi's, returns the first item with the guid."""

    def __init__(self, title, items, search_finds=None):
        self.title = title
        self.items = items
        self.search_finds = items if search_finds is None else search_finds

    def getGuid(self, guid):
        return self.items[0]

    def search(self, guid=None, **kwargs):
        return [item for item in self.search_finds if item.guid == guid]


def _connector(*sections):
    connector = PlexConnector()
    connector.plex = object()
    connector.movie_libraries = list(sections)
    return connector


EDITION = _movie(81522, "Alien (1979) {edition-35mm Film Scan}")
PLAIN = _movie(89650, "Alien (1979)")
ARTWORK = {"title": "Alien", "year": 1979, "tmdb_id": 348}


def test_every_edition_in_a_library_is_returned():
    connector = _connector(_Section("Movies", [EDITION, PLAIN]))

    items, libraries = connector.find_in_library("movie", dict(ARTWORK))

    assert items == [EDITION, PLAIN]
    assert libraries == ["Movies", "Movies"]


def test_each_library_contributes_its_own_copies():
    uhd = _movie(90001, "Alien (1979)")
    connector = _connector(_Section("Movies", [EDITION, PLAIN]), _Section("4K Movies", [uhd]))

    items, libraries = connector.find_in_library("movie", dict(ARTWORK))

    assert items == [EDITION, PLAIN, uhd]
    assert libraries == ["Movies", "Movies", "4K Movies"]


def test_a_guid_search_that_finds_nothing_keeps_the_item_getguid_found():
    connector = _connector(_Section("Movies", [PLAIN], search_finds=[]))

    items, libraries = connector.find_in_library("movie", dict(ARTWORK))

    assert items == [PLAIN]
    assert libraries == ["Movies"]


def test_a_known_import_path_still_narrows_to_the_item_holding_it():
    connector = _connector(_Section("Movies", [EDITION, PLAIN]))
    artwork = dict(ARTWORK, media_folder="Alien (1979)", media_file=("Alien (1979).mkv",))

    items, _ = connector.find_in_library("movie", artwork)

    assert items == [PLAIN]
