"""Unit tests for cook_soup (utils/soup_utils.py)."""

import pytest

from core.exceptions import ScraperException
from utils.soup_utils import cook_soup


@pytest.mark.unit
def test_a_local_html_file_comes_back_as_soup(tmp_path):
    page = tmp_path / "poster_page.html"
    page.write_text("<html><body><h1>Poster set</h1></body></html>", encoding="utf-8")

    soup = cook_soup(str(page))

    assert soup.find("h1").text == "Poster set"


@pytest.mark.unit
def test_a_path_that_is_neither_a_url_nor_html_is_refused(tmp_path):
    with pytest.raises(ScraperException) as raised:
        cook_soup(str(tmp_path / "notes.txt"))

    assert "notes.txt" in str(raised.value)


@pytest.mark.unit
def test_a_missing_html_file_is_refused(tmp_path):
    with pytest.raises(ScraperException) as raised:
        cook_soup(str(tmp_path / "gone.html"))

    assert "gone.html" in str(raised.value)
