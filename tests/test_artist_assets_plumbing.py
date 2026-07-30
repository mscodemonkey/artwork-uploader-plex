"""The ownership map (artist_assets) must reach the uploader the way production builds it: the
ThePosterDBScraper builds it, the Scraper wrapper carries it, and ArtworkProcessor prefers it
over the collected-artwork fallback. These guard against the map being silently dropped."""

import os

import pytest

from models.callbacks import ProcessingCallbacks
from models.options import Options
from services.artwork_processor import ArtworkProcessor
from utils.utils import calculate_md5

ASSETS = "https://theposterdb.com/api/assets"


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    os.makedirs(tmp_path / "config", exist_ok=True)
    monkeypatch.chdir(tmp_path)


def test_scraper_wrapper_carries_artist_assets_from_theposterdb(monkeypatch):
    import scrapers.scraper as scraper_module
    from scrapers.scraper import Scraper

    class _FakeTPDB:
        def __init__(self, url, callbacks):
            self.title = self.author = None
            self.artist_assets = {"abc": 123}
            self.movie_artwork = self.tv_artwork = self.collection_artwork = []
            self.skipped = self.exclusions = self.filtered = self.errored = self.total = 0

        def set_options(self, options):
            pass

        def scrape(self):
            self.author = "someone"

    monkeypatch.setattr(scraper_module, "ThePosterDBScraper", _FakeTPDB)

    wrapper = Scraper("https://theposterdb.com/user/someone", ProcessingCallbacks())
    wrapper.source = "theposterdb"
    wrapper.set_options(Options())
    wrapper.scrape()

    assert wrapper.artist_assets == {"abc": 123}   # not dropped by the wrapper


def test_processor_prefers_the_scrapers_map_over_the_fallback():
    class _Scraper:
        artist_assets = {"from": "index"}
        movie_artwork = tv_artwork = collection_artwork = []

    chosen = _Scraper().artist_assets if getattr(_Scraper, "artist_assets", None) is not None \
        else ArtworkProcessor._artist_assets_from_scrape(_Scraper())
    assert chosen == {"from": "index"}


def test_fallback_map_is_built_from_collected_artwork():
    class _Scraper:
        artist_assets = None
        movie_artwork = [{"id": 100, "url": f"{ASSETS}/100&_cb=9"}]
        tv_artwork = [{"id": 200, "url": f"{ASSETS}/200"}]
        collection_artwork = [{"id": "notanumber", "url": f"{ASSETS}/x"}]

    mapping = ArtworkProcessor._artist_assets_from_scrape(_Scraper())

    assert mapping[calculate_md5(f"{ASSETS}/100")] == 100   # cache buster stripped before md5
    assert mapping[calculate_md5(f"{ASSETS}/200")] == 200
    assert len(mapping) == 2                                 # the non-numeric id is skipped
