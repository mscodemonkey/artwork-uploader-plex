"""
Regression tests for MediuxScraper collection handling.

Covers the bug where scraping a movie collection whose name does not contain the
literal word "Collection" raised:
    UnboundLocalError: cannot access local variable 'year' ...
because collection artwork was mis-routed into the movie branch (which references
`year`, only set for individual-movie artwork).
"""

from unittest.mock import patch

import pytest

from models.options import Options
from scrapers.mediux_scraper import MediuxScraper


class _NoopCallbacks:
    """Every callback (debug/log/...) is a no-op that still evaluates its args."""

    def __getattr__(self, _name):
        return lambda *a, **k: None


def _make_scraper():
    # Avoid touching config.json / Plex; just exercise _process_set in isolation.
    with patch("core.config.Config.load", lambda self: None):
        scraper = MediuxScraper(url="test", callbacks=_NoopCallbacks())
    scraper.set_options(Options())  # defaults: no filters, no exclusions
    scraper.config.mediux_filters = ["collection_poster", "background", "movie_poster"]
    return scraper


def _collection_poster_set(collection_name):
    """A minimal MediUX set payload consisting of a single collection poster."""
    file_entry = {
        "movie_id": None,
        "collection_id": {"id": 1},
        "show_id": None,
        "show_id_backdrop": None,
        "episode_id": None,
        "season_id": None,
        "id": "img123",
        "fileType": "poster",
    }
    return {"files": [file_entry], "collection": {"collection_name": collection_name}}


@pytest.mark.unit
def test_collection_without_word_collection_in_name_does_not_crash():
    # Regression: this used to raise UnboundLocalError on `year`.
    scraper = _make_scraper()
    scraper._process_set(_collection_poster_set("James Bond"))
    assert len(scraper.collection_artwork) == 1
    assert scraper.collection_artwork[0]["title"] == "James Bond"
    assert scraper.collection_artwork[0]["type"] == "collection_poster"


@pytest.mark.unit
def test_collection_with_word_collection_in_name_still_works():
    scraper = _make_scraper()
    scraper._process_set(_collection_poster_set("James Bond Collection"))
    assert len(scraper.collection_artwork) == 1
    assert scraper.collection_artwork[0]["title"] == "James Bond Collection"
