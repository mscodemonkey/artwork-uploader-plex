"""Unit tests for run-summary counters, ProcessingCallbacks result recording, and RunOutcome rules."""

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

import core.globals as globals
from artwork_uploader import parse_bulk_file_from_cli, process_bulk_import_from_ui
from core.enums import RunOutcome
from models.callbacks import ProcessingCallbacks
from models.instance import Instance
from processors.upload_processor import UploadProcessor
from services.run_history import RunHistory


@pytest.mark.parametrize("result, expected", [
    ("✅ A Movie | Poster updated in Movies", "success"),
    ("♻️ A Movie | Poster forced update in Movies", "success"),
    ("🔒 A Movie | Poster locked, skipped in Movies", "locked"),
    ("❌ A Movie | Failed to update Poster in Movies", "failed"),
    ("⏩ A Movie | Poster unchanged in Movies", None),
    ("⚠️ A Movie | Poster skipped - artwork is for a different title", None),
    ("Plex API not available at endpoint", "unavailable"),
])
def test_record_result_reads_uploader_prefixes(result, expected):
    """Verify that record_result maps string prefixes to the correct status category."""
    callbacks = ProcessingCallbacks()
    assert callbacks.record_result(result) == expected


def test_record_result_populates_counters_and_updated_asset_map():
    """Verify that record_result updates counter metrics and builds updated_asset_map correctly."""
    callbacks = ProcessingCallbacks()
    
    artwork = {
        "library": "TV Shows",
        "ratingKey": 418617,
        "title": "VisionQuest",
        "year": 2026,
        "media_type": "episode",
        "season": "1",        # Intended string to test numeric conversion
        "episode": "3",       # Intended string to test numeric conversion
        "file_type": "poster",
        "author": "RandalPink87",
        "overlay": True,
        "status": "refreshed"
    }

    status = callbacks.record_result("✅ Title card refreshed", artwork=artwork)
    
    assert status == "success"
    assert callbacks.assets_processed[0] == 1
    assert callbacks.success_counter[0] == 1
    
    # Assert structural integrity of updated_asset_map
    assert "TV Shows" in callbacks.updated_asset_map
    assert 418617 in callbacks.updated_asset_map["TV Shows"]
    
    entry = callbacks.updated_asset_map["TV Shows"][418617]
    assert entry["title"] == "VisionQuest"
    assert entry["year"] == 2026
    assert len(entry["updated_assets"]) == 1
    
    asset_meta = entry["updated_assets"][0]
    assert asset_meta["season"] == 1  # Verify type conversion to int
    assert asset_meta["episode"] == 3  # Verify type conversion to int
    assert asset_meta["overlay"] is True

def test_upload_processor_tallying_locked_and_successes():
    """Verify UploadProcessor records locked and successful items through callbacks correctly."""
    locked, success = [0], [0]
    callbacks = ProcessingCallbacks(locked_counter=locked, success_counter=success)
    uploader = UploadProcessor(plex=None, callbacks=callbacks)

    # Simulate UploadProcessor calling record_result during operations
    uploader.callbacks.record_result("✅ A Movie | Poster updated in Movies")
    uploader.callbacks.record_result("🔒 B Movie | Poster locked, skipped in Movies")
    uploader.callbacks.record_result("🔒 C Movie | Poster locked, skipped in Movies")
    uploader.callbacks.record_result("⏩ D Movie | Poster unchanged in Movies")

    assert locked[0] == 2
    assert success[0] == 1


def test_upload_processor_tallying_failed_uploads():
    """Verify failed upload attempts increment the failed counter without affecting success."""
    success, failed = [0], [0]
    callbacks = ProcessingCallbacks(success_counter=success, failed_counter=failed)
    uploader = UploadProcessor(plex=None, callbacks=callbacks)

    uploader.callbacks.record_result("✅ A Movie | Poster updated in Movies")
    uploader.callbacks.record_result("❌ B Movie | Failed to update Poster in Movies after 3 attempt(s): timed out")

    assert success[0] == 1
    assert failed[0] == 1

def test_locked_counter_increments():
    locked = [0]
    callbacks = ProcessingCallbacks(locked_counter=locked)
    callbacks.locked(1)
    callbacks.locked(2)
    assert locked[0] == 3


def test_counter_methods_are_no_ops_without_target_counters():
    callbacks = ProcessingCallbacks(
        success_counter=None,
        locked_counter=None,
        failed_counter=None
    )
    callbacks.locked(1)
    callbacks.failed(1)
    callbacks.success(1)
    callbacks.assets(1)
    # Must complete without raising AttributeError / TypeError

def _counter_field_names():
    """Read the counters off the class rather than listing them here, so one added later
    is covered without anybody remembering to update this test."""
    return [field.name for field in dataclasses.fields(ProcessingCallbacks)
            if not field.name.startswith("on_")]


def _callbacks_built_by(start_the_run, tmp_path):
    """Execute a run with stubbed dependencies and extract the generated ProcessingCallbacks."""
    with (
        patch("artwork_uploader.ArtworkProcessor") as processor_class,
        patch("artwork_uploader.RunHistory", lambda: RunHistory(str(tmp_path / "run_history.json"))),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_log"),
        patch("artwork_uploader.update_status"),
        patch("artwork_uploader.debug_me"),
    ):
        processor_class.return_value.scrape_and_process.return_value = ("A Title", "An Author")
        start_the_run()

    assert processor_class.call_count == 1, "The target execution path did not reach ArtworkProcessor"
    return processor_class.call_args.args[1]


@pytest.fixture
def plex_configured():
    globals.plex = MagicMock(tv_libraries=MagicMock(), movie_libraries=MagicMock())
    globals.config = MagicMock(apprise_urls=[])
    try:
        yield
    finally:
        globals.plex = None
        globals.config = None
        globals.cancel_scrape = False
        globals.scrapes_running = 0


@pytest.mark.unit
def test_the_command_line_bulk_path_passes_every_counter(tmp_path, plex_configured):
    bulk_file = tmp_path / "nightly.txt"
    bulk_file.write_text("https://mediux.pro/sets/12345\n", encoding="utf-8")

    callbacks = _callbacks_built_by(
        lambda: parse_bulk_file_from_cli(Instance(mode="cli"), str(bulk_file)), tmp_path
    )

    assert [name for name in _counter_field_names() if getattr(callbacks, name) is None] == []


@pytest.mark.unit
def test_the_bulk_import_tab_path_passes_every_counter(tmp_path, plex_configured):
    callbacks = _callbacks_built_by(
        lambda: process_bulk_import_from_ui(Instance(mode="cli"), [MagicMock()], "nightly.txt"), tmp_path
    )

    assert [name for name in _counter_field_names() if getattr(callbacks, name) is None] == []


# The outcome ladder used to be written out once per path that records a run, and the copies
# had drifted: the Bulk Import tab could not record skipped at all, so a file that processed
# nothing was stored as a success while the same file from the scrape tab, a ZIP upload or the
# command line was stored as skipped. It is worked out on the tally now, so there is one copy.

def test_a_run_that_processed_something_cleanly_is_a_success():
    tally = ProcessingCallbacks()
    tally.assets(3)
    tally.success(2)

    assert tally.outcome() == RunOutcome.SUCCESS.value


def test_a_run_that_processed_nothing_is_skipped():
    assert ProcessingCallbacks().outcome() == RunOutcome.SKIPPED.value


def test_an_upload_that_exhausted_its_retries_makes_the_run_partial():
    tally = ProcessingCallbacks()
    tally.assets(2)
    tally.success(1)
    tally.failed(1)

    assert tally.outcome() == RunOutcome.PARTIAL.value
    assert tally.errors() == 1


def test_errors_the_caller_counted_itself_make_the_run_partial():
    """A bulk import line that could not be scraped at all never reaches the uploader,
    so the caller counts it and hands it over."""
    tally = ProcessingCallbacks()
    tally.assets(1)
    tally.success(1)

    assert tally.outcome(extra_errors=1) == RunOutcome.PARTIAL.value
    assert tally.errors(1) == 1


def test_stopped_beats_everything_else():
    tally = ProcessingCallbacks()
    tally.assets(1)
    tally.failed(1)

    assert tally.outcome(stopped=True) == RunOutcome.STOPPED.value


def test_a_path_with_no_stop_button_never_reports_stopped():
    """Only the paths that have a Stop button pass stopped, so a run started from the
    command line cannot report it however the run went."""
    tally = ProcessingCallbacks()
    tally.assets(1)

    assert tally.outcome() == RunOutcome.SUCCESS.value