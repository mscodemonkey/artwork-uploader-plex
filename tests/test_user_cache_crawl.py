"""Tests for the cached user-crawl: stopping at the end of the uploads, not tombstoning a
catalogue from a crawl that was cut short, and reporting new assets added to the cache."""

import os

import pytest

from models.callbacks import ProcessingCallbacks
from models.options import Options
from services.asset_index import AssetIndex
import scrapers.theposterdb_scraper as tpdb
from scrapers.theposterdb_scraper import ThePosterDBScraper


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    os.makedirs(tmp_path / "config", exist_ok=True)
    monkeypatch.chdir(tmp_path)


def _asset(asset_id):
    return {
        "id": asset_id,
        "title": f"Film {asset_id}",
        "year": 2020,
        "season": None,
        "media_type": "movie_poster",
        "author": "someone",
        "url": f"https://theposterdb.com/api/assets/{asset_id}",
    }


def _scraper(counters=None):
    scraper = ThePosterDBScraper("https://theposterdb.com/user/someone",
                                 ProcessingCallbacks(**(counters or {})))
    scraper.set_options(Options())
    scraper.author = "someone"
    return scraper


def _fill(pages):
    """Return a fake scrape_user_page that fills the catalog from `pages` (dict page->id list)."""
    fetched = []

    def fake(page, catalog=None):
        fetched.append(page)
        for asset_id in pages.get(page, []):
            catalog.append(_asset(asset_id))
        return True

    fake.fetched = fetched
    return fake


# --- A2: stop at the end of the uploads, don't poison a clean crawl ----------------------------

def test_crawl_stops_at_empty_page_without_marking_it_unclean(tmp_path, monkeypatch):
    scraper = _scraper()
    scraper.user_uploads = 120
    scraper.user_pages = 5                       # counter overshoots: only 2 pages hold assets
    index = AssetIndex(str(tmp_path / "idx.db"))
    fake = _fill({0: range(1000, 1024), 1: range(2000, 2024)})
    monkeypatch.setattr(scraper, "scrape_user_page", fake)

    new_rows, seen_ids, clean = scraper._crawl_user_pages(index, "someone", full=True)

    assert fake.fetched == [0, 1, 2]             # stopped AT the first empty page
    assert clean is True                         # a trailing empty page is not a failure
    assert len(seen_ids) == 48


def test_a_failed_page_still_marks_the_crawl_unclean(tmp_path, monkeypatch):
    scraper = _scraper()
    scraper.user_uploads = 72
    scraper.user_pages = 3
    index = AssetIndex(str(tmp_path / "idx.db"))

    def fake(page, catalog=None):
        if page == 1:
            return False                         # a genuine fetch failure, not an empty page
        for asset_id in range(page * 1000, page * 1000 + 24):
            catalog.append(_asset(asset_id))
        return True

    monkeypatch.setattr(scraper, "scrape_user_page", fake)
    new_rows, seen_ids, clean = scraper._crawl_user_pages(index, "someone", full=True)

    assert clean is False                        # a real failure must still block reconcile


# --- reconcile guard: never tombstone from a crawl that was cut short --------------------------

def _seed(tmp_path, n):
    index = AssetIndex(str(tmp_path / "idx.db"))
    index.record("someone", [_asset(i) for i in range(n)])
    index.record_crawl("someone", True, n)
    return index


def _run_full_crawl(scraper, tmp_path, monkeypatch, page_zero_ids):
    scraper.options.no_cache = True              # force a full crawl
    monkeypatch.setattr(tpdb, "AssetIndex", lambda: AssetIndex(str(tmp_path / "idx.db")))
    monkeypatch.setattr(scraper, "_hydrate_from_cache", lambda *a, **k: None)
    fake = _fill({0: page_zero_ids})             # page 1 is empty -> crawl stops after it
    monkeypatch.setattr(scraper, "scrape_user_page", fake)
    scraper._scrape_user_cached()


def test_short_full_crawl_does_not_tombstone(tmp_path, monkeypatch):
    # Index has 100 assets. A full crawl that reaches only 10 of the reported 100 (a broken page,
    # not a real shrink) must NOT tombstone the other 90.
    index = _seed(tmp_path, 100)
    scraper = _scraper()
    scraper.user_uploads = 100
    scraper.user_pages = 50

    _run_full_crawl(scraper, tmp_path, monkeypatch, page_zero_ids=range(0, 10))

    live = index.assets_for_user("someone")
    assert len(live) == 100                       # coverage 10% < 90% -> nothing tombstoned


def test_full_crawl_with_good_coverage_tombstones_deleted(tmp_path, monkeypatch):
    # Index has 100. The user really deleted 2, so the crawl sees 98 of a reported 98. Coverage is
    # high, so the 2 that vanished are tombstoned as normal.
    index = _seed(tmp_path, 100)
    scraper = _scraper()
    scraper.user_uploads = 98
    scraper.user_pages = 50

    _run_full_crawl(scraper, tmp_path, monkeypatch, page_zero_ids=range(0, 98))

    live = index.assets_for_user("someone")
    assert len(live) == 98                         # coverage 100% >= 90% -> 98,99 tombstoned


# --- the "new in cache" counter ----------------------------------------------------------------

def test_new_assets_are_reported_through_the_cached_counter(tmp_path, monkeypatch):
    cached = [0]
    scraper = _scraper({"cached_counter": cached})
    scraper.user_uploads = 48
    scraper.user_pages = 5
    monkeypatch.setattr(tpdb, "AssetIndex", lambda: AssetIndex(str(tmp_path / "idx.db")))
    monkeypatch.setattr(scraper, "_hydrate_from_cache", lambda *a, **k: None)
    fake = _fill({0: range(1000, 1024), 1: range(2000, 2024)})
    monkeypatch.setattr(scraper, "scrape_user_page", fake)

    scraper._scrape_user_cached()

    assert cached[0] == 48                          # all 48 were new to the cache


# --- regression: hydrate must key artwork as file_type, exactly as get_posters does ------------

def test_hydrate_from_cache_uses_the_processor_file_type_key(tmp_path):
    """_hydrate_from_cache rebuilds the artwork lists that feed the upload processor, so its dicts
       must carry 'file_type' (what get_posters writes and the processor reads), not 'type'. With
       'type', ARTWORK_ID_MAP.get(...) is None and the uploader crashes on None + md5 - the same
       fault that broke the import webhook, latent here until a cached crawl meets an unlocked
       in-library item."""
    from core.constants import ARTWORK_ID_MAP

    index = AssetIndex(str(tmp_path / "idx.db"))
    index.record("someone", [
        {"id": 1, "title": "Dune", "year": 2021, "season": None,
         "media_type": "movie_poster", "author": "someone",
         "url": "https://theposterdb.com/api/assets/1"},
        {"id": 2, "title": "Severance", "year": 2022, "season": None,
         "media_type": "show_cover", "author": "someone",
         "url": "https://theposterdb.com/api/assets/2"},
        {"id": 3, "title": "Severance", "year": 2022, "season": 1,
         "media_type": "season_cover", "author": "someone",
         "url": "https://theposterdb.com/api/assets/3"},
    ])

    scraper = _scraper()
    scraper.config.tpdb_filters = ["movie_poster", "show_cover", "season_cover", "collection_poster"]
    scraper._hydrate_from_cache(index, "someone")

    produced = scraper.movie_artwork + scraper.tv_artwork
    assert produced, "hydrate produced no artwork - fixture/filter setup is wrong"
    for artwork in produced:
        assert "file_type" in artwork, f"hydrated artwork missing file_type: {artwork}"
        assert ARTWORK_ID_MAP.get(artwork["file_type"]) is not None
