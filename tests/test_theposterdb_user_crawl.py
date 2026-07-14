"""Unit tests for the ThePosterDB user-uploads crawl.

These drive the real scrape_user_page / get_posters path with HTML fixtures and stub only the
network (cook_soup), so a change that turns the crawl into a no-op is caught rather than hidden.
"""

import os

import pytest
from bs4 import BeautifulSoup

from models.callbacks import ProcessingCallbacks
from models.options import Options
from scrapers.theposterdb_scraper import ThePosterDBScraper

POSTER_GRID_CLASS = "row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1"


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    # Config.load() writes config/config.json when it's missing; keep that out of the repo.
    os.makedirs(tmp_path / "config", exist_ok=True)
    monkeypatch.chdir(tmp_path)


def _poster_tile(poster_id, title):
    return f"""
    <div class="col-6 col-lg-2 p-1">
      <a class="text-white" data-toggle="tooltip" data-placement="top" title="Movie">x</a>
      <div class="overlay" data-poster-id="{poster_id}"></div>
      <p class="p-0 mb-1 text-break">{title}</p>
    </div>
    """


def _user_page(n_tiles, start_id=1000):
    tiles = "".join(_poster_tile(start_id + i, f"Film {start_id + i} (2020)") for i in range(n_tiles))
    return BeautifulSoup(f'<div class="{POSTER_GRID_CLASS}">{tiles}</div>', "html.parser")


def _base_user_page(count, author="someone"):
    return BeautifulSoup(
        f'<span class="numCount" data-count="{count}"></span>'
        f'<p class="h1 mb-0 mr-md-1"><a>{author}</a></p>',
        "html.parser",
    )


def _scraper(url="https://theposterdb.com/user/someone"):
    scraper = ThePosterDBScraper(url, ProcessingCallbacks())
    scraper.set_options(Options())
    return scraper


# --- get_posters robustness (the crash site) ---------------------------------------------------

def test_get_posters_on_a_missing_grid_does_not_raise():
    # numCount can overshoot the pages actually listed, so the crawl can request a page past the
    # last real one. scrape_posters passes get_posters a None grid for such a page.
    scraper = _scraper()
    scraper.get_posters(None)
    assert scraper.total == 0


def test_get_posters_on_an_empty_grid_does_not_raise():
    scraper = _scraper()
    empty = BeautifulSoup(f'<div class="{POSTER_GRID_CLASS}"></div>', "html.parser").div
    scraper.get_posters(empty)
    assert scraper.total == 0


# --- scrape_user_page reports success/failure --------------------------------------------------

def test_scrape_user_page_returns_true_on_success(monkeypatch):
    scraper = _scraper()
    monkeypatch.setattr("utils.soup_utils.cook_soup", lambda url: _user_page(3))
    assert scraper.scrape_user_page(0) is True
    assert scraper.total == 3


def test_scrape_user_page_returns_false_when_the_fetch_fails(monkeypatch):
    scraper = _scraper()

    def boom(url):
        raise RuntimeError("network down")

    monkeypatch.setattr("utils.soup_utils.cook_soup", boom)
    assert scraper.scrape_user_page(0) is False


# --- the crawl stops at the end of the uploads -------------------------------------------------

def test_crawl_stops_at_the_first_empty_page(monkeypatch):
    # Counter claims 120 uploads (5 pages); only the first two actually hold assets. The crawl
    # must stop at the first empty page and NOT fetch pages 4 and 5. Asserting on the pages
    # actually fetched (not just the asset total, which is 48 either way) is what makes this
    # detect a crawl that silently ploughs on to the end of the counter's page count.
    scraper = _scraper()
    fetched = []
    pages = {1: _user_page(24, 1000), 2: _user_page(24, 2000)}

    def fake_cook_soup(url):
        if "section=uploads" not in url:
            return _base_user_page(120)
        page = int(url.split("page=")[1])
        fetched.append(page)
        return pages.get(page, _user_page(0))   # pages 3+ are empty

    monkeypatch.setattr("utils.soup_utils.cook_soup", fake_cook_soup)
    scraper.scrape()

    assert fetched == [1, 2, 3]                  # stopped AT the first empty page, 4 and 5 untouched
    assert scraper.total == 48


def test_crawl_does_not_stop_on_a_failed_page(monkeypatch):
    # A failed page also adds nothing to total, but it is not the end of the list, so the crawl
    # must carry on to the pages after it rather than mistaking a failure for the end.
    scraper = _scraper()
    fetched = []

    def fake_cook_soup(url):
        if "section=uploads" not in url:
            return _base_user_page(72)          # 3 pages
        page = int(url.split("page=")[1])
        fetched.append(page)
        if page == 2:
            raise RuntimeError("transient")
        return _user_page(24, page * 1000)

    monkeypatch.setattr("utils.soup_utils.cook_soup", fake_cook_soup)
    scraper.scrape()

    assert fetched == [1, 2, 3]                  # page 2 failed but the crawl continued to page 3
    assert scraper.total == 48                   # pages 1 and 3 contributed
