"""
Tests that the library index does not trust an entry it read before Plex had matched the item.

Plex creates a new item a few seconds before its agent match lands, so an index built inside that
window stores the title with no TMDb ID. The index only rebuilds when the library's count or newest
item changes, and both are already final by then, so the entry would otherwise stay wrong until the
index expires. These cover the lookup reading the item's guids from Plex again when the entry has none.
"""

import pytest

from core.enums import MediaType
from plex.library_index import PlexLibraryIndex


class _FakeGuid:
    def __init__(self, guid_id):
        self.id = guid_id


class _FakeItem:
    def __init__(self, rating_key, title, year, guids=()):
        self.ratingKey = rating_key
        self.title = title
        self.year = year
        self.guids = [_FakeGuid(guid) for guid in guids]
        self.slug = None
        self.originalTitle = None
        self.addedAt = None
        self._autoReload = True


class _FakeLibrary:
    def __init__(self, title, items):
        self.title = title
        self.type = "show"
        self.items = items
        self.fetched = []

    def reload(self):
        return self

    @property
    def totalSize(self):
        return len(self.items)

    def search(self, sort=None, limit=None):
        return self.items[:1]

    def all(self):
        return list(self.items)

    def fetchItem(self, rating_key):
        self.fetched.append(rating_key)
        for item in self.items:
            if item.ratingKey == rating_key:
                return item
        raise LookupError(rating_key)


def _index_with(item):
    library = _FakeLibrary("TV Shows", [item])
    return PlexLibraryIndex([], [library]), library


@pytest.mark.unit
def test_an_entry_indexed_before_plex_matched_it_picks_up_the_guid_on_lookup():
    item = _FakeItem(89610, "Slow Horses", 2022)
    index, library = _index_with(item)

    # Plex finishes its agent match after the index was built.
    item.guids = [_FakeGuid("tmdb://95480"), _FakeGuid("tvdb://372264")]

    status, match = index.lookup("Slow Horses", 2022, MediaType.TV_SHOW)

    assert status == "matched"
    assert match["tmdb_id"] == 95480
    assert library.fetched == [89610]


@pytest.mark.unit
def test_a_refreshed_entry_is_not_fetched_again():
    item = _FakeItem(89610, "Slow Horses", 2022)
    index, library = _index_with(item)
    item.guids = [_FakeGuid("tmdb://95480")]

    index.lookup("Slow Horses", 2022, MediaType.TV_SHOW)
    status, match = index.lookup("Slow Horses", 2022, MediaType.TV_SHOW)

    assert status == "matched"
    assert match["tmdb_id"] == 95480
    assert library.fetched == [89610]


@pytest.mark.unit
def test_an_entry_still_without_a_tmdb_id_is_asked_for_again_on_every_lookup():
    item = _FakeItem(89610, "Slow Horses", 2022)
    index, library = _index_with(item)

    index.lookup("Slow Horses", 2022, MediaType.TV_SHOW)
    status, match = index.lookup("Slow Horses", 2022, MediaType.TV_SHOW)

    assert status == "matched"
    assert match["tmdb_id"] is None
    assert library.fetched == [89610, 89610]


@pytest.mark.unit
def test_a_failed_refresh_leaves_the_entry_as_it_was():
    item = _FakeItem(89610, "Slow Horses", 2022)
    index, library = _index_with(item)

    def _down(_rating_key):
        raise ConnectionError("Plex went away")

    library.fetchItem = _down

    status, match = index.lookup("Slow Horses", 2022, MediaType.TV_SHOW)

    assert status == "matched"
    assert match["tmdb_id"] is None


@pytest.mark.unit
def test_an_entry_with_a_tmdb_id_is_never_fetched():
    item = _FakeItem(89610, "Slow Horses", 2022, guids=["tmdb://95480"])
    index, library = _index_with(item)

    status, match = index.lookup("Slow Horses", 2022, MediaType.TV_SHOW)

    assert status == "matched"
    assert match["tmdb_id"] == 95480
    assert library.fetched == []
