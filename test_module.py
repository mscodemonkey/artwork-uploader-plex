"""
Test module for Artwork Uploader scrapers.

Run with: pytest test_module.py -v
"""

import pytest
from theposterdb_scraper import ThePosterDBScraper
from mediux_scraper import MediuxScraper
from enums import ScraperSource


def test_scrape_posterdb_set_tv_series():
    """Test scraping a TV series set from ThePosterDB."""
    scraper = ThePosterDBScraper("https://theposterdb.com/set/8846")
    scraper.scrape()

    assert len(scraper.movie_artwork) == 0
    assert len(scraper.collection_artwork) == 0
    assert len(scraper.tv_artwork) == 10

    for showposter in scraper.tv_artwork:
        assert showposter["title"] == "Brooklyn Nine-Nine"
        assert showposter["year"] == 2013
        assert showposter["episode"] is None
        assert showposter["season"] == "Cover" or (0 <= showposter["season"] <= 8)
        assert showposter["source"] == ScraperSource.THEPOSTERDB.value


def test_scrape_posterdb_set_movie_collection():
    """Test scraping a movie collection from ThePosterDB."""
    scraper = ThePosterDBScraper("https://theposterdb.com/set/13035")
    scraper.scrape()

    assert len(scraper.movie_artwork) == 3
    assert len(scraper.collection_artwork) == 1
    assert len(scraper.tv_artwork) == 0

    for collectionposter in scraper.collection_artwork:
        assert collectionposter["title"] == "The Dark Knight Collection"
        assert collectionposter["source"] == ScraperSource.THEPOSTERDB.value


def test_scrape_mediux_set_tv_series():
    """Test scraping a TV series set from MediUX."""
    scraper = MediuxScraper("https://mediux.pro/sets/9242")
    scraper.scrape()

    assert len(scraper.movie_artwork) == 0
    assert len(scraper.collection_artwork) == 0
    assert len(scraper.tv_artwork) == 11

    backdrop_count = 0
    episode_count = 0
    cover_count = 0

    for showposter in scraper.tv_artwork:
        assert showposter["title"] == "Mr. & Mrs. Smith"
        assert showposter["year"] == 2024
        assert showposter["source"] == ScraperSource.MEDIUX.value

        if isinstance(showposter["episode"], int):
            episode_count += 1
        elif showposter["episode"] == "Cover":
            cover_count += 1
        elif showposter["season"] == "Cover":
            cover_count += 1
        elif showposter["season"] == "Backdrop":
            backdrop_count += 1

    assert backdrop_count == 1
    assert episode_count == 8
    assert cover_count == 2


def test_scrape_mediux_set_tv_series_long():
    """Test scraping a long TV series set from MediUX."""
    scraper = MediuxScraper("https://mediux.pro/sets/13427")
    scraper.scrape()

    assert len(scraper.movie_artwork) == 0
    assert len(scraper.collection_artwork) == 0
    assert len(scraper.tv_artwork) == 264

    backdrop_count = 0
    episode_count = 0
    cover_count = 0

    for showposter in scraper.tv_artwork:
        assert showposter["title"] == "Modern Family"
        assert showposter["year"] == 2009
        assert showposter["source"] == ScraperSource.MEDIUX.value

        if isinstance(showposter["episode"], int):
            episode_count += 1
        elif showposter["episode"] == "Cover":
            cover_count += 1
        elif showposter["season"] == "Cover":
            cover_count += 1
        elif showposter["season"] == "Backdrop":
            backdrop_count += 1

    assert backdrop_count == 1
    assert episode_count == 250
    assert cover_count == 13


def test_scrape_mediux_boxset():
    """Test scraping a large box set from MediUX."""
    scraper = MediuxScraper("https://mediux.pro/sets/9406")
    scraper.scrape()

    assert len(scraper.movie_artwork) == 0
    assert len(scraper.collection_artwork) == 0
    assert len(scraper.tv_artwork) == 247

    backdrop_count = 0
    episode_count = 0
    cover_count = 0

    for showposter in scraper.tv_artwork:
        assert showposter["title"] == "Doctor Who"
        assert showposter["year"] == 2005
        assert showposter["source"] == ScraperSource.MEDIUX.value

        if isinstance(showposter["episode"], int):
            episode_count += 1
        elif showposter["episode"] == "Cover":
            cover_count += 1
        elif showposter["season"] == "Cover":
            cover_count += 1
        elif showposter["season"] == "Backdrop":
            backdrop_count += 1

    assert backdrop_count == 0
    assert episode_count == 232
    assert cover_count == 15


if __name__ == "__main__":
    # Run a quick test if executed directly
    print("Running quick test...")
    test_scrape_mediux_set_tv_series()
    print("✓ Quick test passed!")
