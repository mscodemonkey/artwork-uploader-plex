"""
Covers the run history record process_scrape_url_from_web writes.

A single URL scraped from the main tab does the same work to Plex a bulk import line
does, so it leaves the same kind of record. Every way out of the function is exercised
here, including the ones that never reach the scraper, because a run that failed to
start is exactly the run somebody goes looking for afterwards.
"""

from unittest.mock import MagicMock, patch

import pytest

import core.globals as globals
from artwork_uploader import process_scrape_url_from_web
from models.instance import Instance
from services.run_history import RunHistory
from core.enums import RunType, RunTrigger, RunOutcome

OUTCOME_SUCCESS = RunOutcome.SUCCESS.value
OUTCOME_PARTIAL = RunOutcome.PARTIAL.value
OUTCOME_STOPPED = RunOutcome.STOPPED.value
OUTCOME_FAILED = RunOutcome.FAILED.value
OUTCOME_SKIPPED = RunOutcome.SKIPPED.value
RUN_TYPE_SCRAPE = RunType.SCRAPE.value
TRIGGER_MANUAL = RunTrigger.MANUAL.value

URL = "https://theposterdb.com/set/12345"


@pytest.fixture
def history(tmp_path, monkeypatch):
    real_history = RunHistory(str(tmp_path / "run_history.json"))
    monkeypatch.setattr("artwork_uploader.RunHistory", lambda: real_history)
    return real_history


@pytest.fixture(autouse=True)
def reset_globals():
    try:
        yield
    finally:
        globals.cancel_scrape = False
        globals.scrapes_running = 0
        globals.plex = None
        globals.config = None


@pytest.fixture
def configured_plex():
    globals.plex = MagicMock(tv_libraries=MagicMock(), movie_libraries=MagicMock())
    globals.config = MagicMock(apprise_urls=[])
    return globals.plex


def _scrape(**counts):
    """A stand-in for scrape_and_upload that moves the counters on the tally it is handed."""
    def fake_scrape(instance, url, options, bulk=None, tally=None):
        movers = {
            "assets": tally.assets, "success": tally.success, "cached": tally.cached,
            "locked": tally.locked, "failed": tally.failed,
        }
        for name, count in counts.items():
            movers[name](count)
        return "A Set", "someone"
    return fake_scrape


@pytest.mark.unit
def test_a_scrape_is_recorded_with_its_counters(history, configured_plex):
    with (
        patch("artwork_uploader.scrape_and_upload", side_effect=_scrape(assets=3, success=2, cached=1, locked=1)),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
    ):
        process_scrape_url_from_web(Instance(mode="cli"), URL)

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["run_type"] == RUN_TYPE_SCRAPE
    assert runs[0]["trigger"] == TRIGGER_MANUAL
    assert runs[0]["label"] == URL
    assert runs[0]["outcome"] == OUTCOME_SUCCESS
    assert runs[0]["assets_processed"] == 3
    assert runs[0]["success_count"] == 2
    assert runs[0]["cached_count"] == 1
    assert runs[0]["locked_count"] == 1
    assert runs[0]["error_count"] == 0


@pytest.mark.unit
def test_the_options_are_stripped_from_the_recorded_url(history, configured_plex):
    """The main tab appends the chosen options to the URL. The history records the URL
    that was scraped, not the whole command line."""
    with (
        patch("artwork_uploader.scrape_and_upload", side_effect=_scrape(assets=1, success=1)),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
    ):
        process_scrape_url_from_web(Instance(mode="cli"), f"{URL} --force --year 2021")

    assert history.get_runs()[0]["label"] == URL


@pytest.mark.unit
def test_an_upload_that_exhausted_its_retries_is_recorded_as_partial(history, configured_plex):
    with (
        patch("artwork_uploader.scrape_and_upload", side_effect=_scrape(assets=2, success=1, failed=1)),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
    ):
        process_scrape_url_from_web(Instance(mode="cli"), URL)

    runs = history.get_runs()
    assert runs[0]["outcome"] == OUTCOME_PARTIAL
    assert runs[0]["error_count"] == 1


@pytest.mark.unit
def test_a_scrape_that_processed_nothing_is_recorded_as_skipped(history, configured_plex):
    with (
        patch("artwork_uploader.scrape_and_upload", side_effect=_scrape()),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
    ):
        process_scrape_url_from_web(Instance(mode="cli"), URL)

    assert history.get_runs()[0]["outcome"] == OUTCOME_SKIPPED


@pytest.mark.unit
def test_a_cancelled_scrape_is_recorded_as_stopped(history, configured_plex):
    def cancel_midway(*args, **kwargs):
        globals.cancel_scrape = True
        return None, None

    with (
        patch("artwork_uploader.scrape_and_upload", side_effect=cancel_midway),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
    ):
        process_scrape_url_from_web(Instance(mode="cli"), URL)

    assert history.get_runs()[0]["outcome"] == OUTCOME_STOPPED


@pytest.mark.unit
def test_a_scraper_error_is_recorded_as_failed(history, configured_plex):
    from core.exceptions import ScraperException

    with (
        patch("artwork_uploader.scrape_and_upload", side_effect=ScraperException("nothing there")),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
    ):
        process_scrape_url_from_web(Instance(mode="cli"), URL)

    assert history.get_runs()[0]["outcome"] == OUTCOME_FAILED


@pytest.mark.unit
def test_plex_not_configured_is_recorded_as_failed_without_scraping(history):
    globals.plex = MagicMock(tv_libraries=[], movie_libraries=[])
    globals.plex.ensure_libraries.return_value = False

    with (
        patch("artwork_uploader.scrape_and_upload") as mock_scrape,
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
    ):
        process_scrape_url_from_web(Instance(mode="cli"), URL)

    mock_scrape.assert_not_called()
    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_FAILED
    assert runs[0]["label"] == URL


@pytest.mark.unit
def test_an_invalid_url_is_still_recorded(history, configured_plex):
    """InvalidUrl isn't a ScraperException, so it leaves through the finally. The run
    still has to land in the history rather than vanish."""
    from core.exceptions import InvalidUrl

    with (
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
        pytest.raises(InvalidUrl),
    ):
        process_scrape_url_from_web(Instance(mode="cli"), "not a url at all")

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_FAILED
    assert runs[0]["label"] == "not a url at all"
