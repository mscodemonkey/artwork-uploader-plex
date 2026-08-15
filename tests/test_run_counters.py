"""Unit tests for the run-summary counters."""

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

import core.globals as globals
from artwork_uploader import parse_bulk_file_from_cli, process_bulk_import_from_ui
from core.enums import RunOutcome
from models.callbacks import ProcessingCallbacks
from models.instance import Instance
from services.artwork_processor import ArtworkProcessor
from services.run_history import RunHistory


@pytest.mark.parametrize("result, expected", [
    ("✅ A Movie | Poster updated in Movies", "success"),
    ("♻️ A Movie | Poster forced update in Movies", "success"),
    ("🔒 A Movie | Poster locked, skipped in Movies", "locked"),
    ("❌ A Movie | Failed to update Poster in Movies", "failed"),
    ("⏩ A Movie | Poster unchanged in Movies", None),
    ("⚠️ A Movie | Poster skipped - artwork is for a different title", None),
])
def test_record_result_reads_the_uploader_prefixes(result, expected):
    """Every caller that tallies a run reads these prefixes, so they are checked once
    here rather than restated in each one."""
    counters = ProcessingCallbacks(success_counter=[0], locked_counter=[0], failed_counter=[0])

    assert counters.record_result(result) == expected


def test_record_result_reads_the_prefix_with_the_default_counters():
    assert ProcessingCallbacks().record_result("✅ A Movie | Poster updated") == "success"


def test_locked_counter_increments():
    locked = [0]
    callbacks = ProcessingCallbacks(locked_counter=locked)
    callbacks.locked(1)
    callbacks.locked(2)
    assert locked[0] == 3


def test_locked_is_a_no_op_without_a_counter():
    ProcessingCallbacks().locked(1)   # must not raise


def test_locked_results_are_counted_and_successes_still_are():
    locked, success = [0], [0]
    callbacks = ProcessingCallbacks(locked_counter=locked, success_counter=success)
    processor = ArtworkProcessor(plex=None, callbacks=callbacks)

    processor._process_single_artwork({}, lambda artwork: [
        "✅ A Movie | Poster updated in Movies",
        "🔒 B Movie | Poster locked, skipped in Movies",
        "🔒 C Movie | Poster locked, skipped in Movies",
        "⏩ D Movie | Poster unchanged in Movies",
    ])

    assert locked[0] == 2
    assert success[0] == 1


def test_failed_counter_increments():
    failed = [0]
    callbacks = ProcessingCallbacks(failed_counter=failed)
    callbacks.failed(1)
    callbacks.failed(2)
    assert failed[0] == 3


def test_failed_is_a_no_op_without_a_counter():
    ProcessingCallbacks().failed(1)   # must not raise


def test_failed_uploads_are_counted_and_do_not_count_as_success():
    # An upload that exhausted its retries returns a ❌ result - it must be counted as a failure
    # and must not also be counted as a success.
    success, failed = [0], [0]
    callbacks = ProcessingCallbacks(success_counter=success, failed_counter=failed)
    processor = ArtworkProcessor(plex=None, callbacks=callbacks)

    processor._process_single_artwork({}, lambda artwork: [
        "✅ A Movie | Poster updated in Movies",
        "❌ B Movie | Failed to update Poster in Movies after 3 attempt(s): timed out",
    ])

    assert success[0] == 1
    assert failed[0] == 1


# Every counter on ProcessingCallbacks used to be a keyword argument defaulting to None, and
# each of the increment methods checks for its list before touching it. Leaving one out of a
# call to scrape_and_upload therefore raised nothing and logged nothing: the number simply
# stayed at zero. That had already happened once per counter. assets_processed, cached_counter,
# locked_counter and failed_counter were each added to the bulk import from the Bulk Import
# tab and none of them reached the command line path, which was still passing only a
# success_counter years later. The counters carry a real default now and the paths share one
# tally, so these two can no longer fail. They stay as a guard on that default.

def _counter_field_names():
    """Read the counters off the class rather than listing them here, so one added later
    is covered without anybody remembering to update this test."""
    return [field.name for field in dataclasses.fields(ProcessingCallbacks)
            if not field.name.startswith("on_")]


def _callbacks_built_by(start_the_run, tmp_path):
    """Run one of the bulk paths with the processor stubbed out, and give back the
    ProcessingCallbacks it handed to it."""
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

    assert processor_class.call_count == 1, "the path under test never reached the processor"
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
