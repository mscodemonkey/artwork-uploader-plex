"""
Covers the run history record process_bulk_import_from_ui writes for each outcome it
can reach: a clean run, a run with per-URL errors, a run that never starts because Plex
isn't configured, and a run that dies on an unexpected exception. test_stop_scrape.py
already covers the cancelled ("stopped") branch; this file covers the rest so every
outcome value RunHistory can be given is actually exercised somewhere.
"""

from unittest.mock import MagicMock, patch

import pytest

import core.globals as globals
from artwork_uploader import process_bulk_import_from_ui, run_bulk_import_scrape_in_thread
from models.instance import Instance
from services.run_history import RunHistory
from core.enums import RunOutcome
OUTCOME_SUCCESS = RunOutcome.SUCCESS.value
OUTCOME_PARTIAL = RunOutcome.PARTIAL.value
OUTCOME_FAILED = RunOutcome.FAILED.value
OUTCOME_SKIPPED = RunOutcome.SKIPPED.value


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


@pytest.mark.unit
def test_successful_run_is_recorded_with_its_counters(history):
    globals.plex = MagicMock(tv_libraries=MagicMock(), movie_libraries=MagicMock())
    globals.config = MagicMock(apprise_urls=[])

    def fake_scrape(instance, url, options, bulk, tally=None):
        tally.assets(1)
        tally.success(1)
        tally.cached(1)

    with (
        patch("artwork_uploader.scrape_and_upload", side_effect=fake_scrape),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_log"),
        patch("artwork_uploader.update_status"),
        patch("artwork_uploader.debug_me"),
    ):
        process_bulk_import_from_ui(Instance(mode="cli"), [MagicMock()], "ok.txt")

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_SUCCESS
    assert runs[0]["assets_processed"] == 1
    assert runs[0]["success_count"] == 1
    assert runs[0]["cached_count"] == 1
    assert runs[0]["error_count"] == 0


@pytest.mark.unit
def test_run_with_scraper_errors_is_recorded_as_partial(history):
    from core.exceptions import ScraperException

    globals.plex = MagicMock(tv_libraries=MagicMock(), movie_libraries=MagicMock())
    globals.config = MagicMock(apprise_urls=[])

    with (
        patch("artwork_uploader.scrape_and_upload", side_effect=ScraperException("bad url")),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_log"),
        patch("artwork_uploader.update_status"),
        patch("artwork_uploader.debug_me"),
    ):
        process_bulk_import_from_ui(Instance(mode="cli"), [MagicMock()], "errors.txt")

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_PARTIAL
    assert runs[0]["error_count"] == 1


@pytest.mark.unit
def test_plex_not_configured_is_recorded_as_failed_without_scraping(history):
    globals.plex = MagicMock(tv_libraries=None, movie_libraries=None)
    globals.config = MagicMock(apprise_urls=[])

    with (
        patch("artwork_uploader.scrape_and_upload") as mock_scrape,
        patch("artwork_uploader.update_status"),
    ):
        process_bulk_import_from_ui(Instance(mode="cli"), [MagicMock()], "unconfigured.txt")

    mock_scrape.assert_not_called()
    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_FAILED
    assert runs[0]["assets_processed"] == 0


@pytest.mark.unit
def test_unexpected_exception_mid_run_is_recorded_as_failed(history):
    globals.plex = MagicMock(tv_libraries=MagicMock(), movie_libraries=MagicMock())
    globals.config = MagicMock(apprise_urls=[])

    with (
        patch("artwork_uploader.scrape_and_upload"),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_log"),
        patch("artwork_uploader.update_status"),
        patch("artwork_uploader.debug_me"),
        patch("artwork_uploader.elapsed_time", side_effect=RuntimeError("boom")),
    ):
        process_bulk_import_from_ui(Instance(mode="cli"), [MagicMock()], "crash.txt")

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_FAILED


@pytest.mark.unit
def test_no_valid_urls_in_the_file_is_recorded_as_skipped(history):
    with patch("artwork_uploader.update_status"):
        run_bulk_import_scrape_in_thread(Instance(mode="cli"), "# just a comment\n", "no_urls.txt")

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_SKIPPED
    assert runs[0]["label"] == "no_urls.txt"


@pytest.mark.unit
def test_no_filename_falls_back_to_the_default_bulk_file_name(history):
    """A None filename must not land in the history (and the UI table) as the string 'null'."""
    with patch("artwork_uploader.update_status"):
        run_bulk_import_scrape_in_thread(Instance(mode="cli"), "# just a comment\n", None)

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["label"] == "bulk_import.txt"


# Both of these describe a bulk import from the Bulk Import tab, which used to work out its
# own outcome and pass its own error count to the history. It counted a line that could not be
# scraped, but not an upload that exhausted its retries, and it had no skipped branch at all.

@pytest.mark.unit
def test_an_upload_that_exhausted_its_retries_is_counted_as_an_error(history):
    globals.plex = MagicMock(tv_libraries=MagicMock(), movie_libraries=MagicMock())
    globals.config = MagicMock(apprise_urls=[])

    def fake_scrape(instance, url, options, bulk, tally=None):
        tally.assets(1)
        tally.failed(1)

    with (
        patch("artwork_uploader.scrape_and_upload", side_effect=fake_scrape),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_log"),
        patch("artwork_uploader.update_status"),
        patch("artwork_uploader.debug_me"),
    ):
        process_bulk_import_from_ui(Instance(mode="cli"), [MagicMock()], "retries.txt")

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_PARTIAL
    assert runs[0]["error_count"] == 1


@pytest.mark.unit
def test_a_run_that_processes_nothing_is_recorded_as_skipped(history):
    globals.plex = MagicMock(tv_libraries=MagicMock(), movie_libraries=MagicMock())
    globals.config = MagicMock(apprise_urls=[])

    with (
        patch("artwork_uploader.scrape_and_upload"),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_log"),
        patch("artwork_uploader.update_status"),
        patch("artwork_uploader.debug_me"),
    ):
        process_bulk_import_from_ui(Instance(mode="cli"), [MagicMock()], "nothing.txt")

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_SKIPPED
    assert runs[0]["assets_processed"] == 0
