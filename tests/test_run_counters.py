"""Unit tests for the run-summary counters."""

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

import core.globals as globals
from artwork_uploader import parse_bulk_file_from_cli, process_bulk_import_from_ui
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


def test_record_result_is_a_no_op_without_counters():
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


# Every counter on ProcessingCallbacks is a keyword argument that defaults to None, and each
# of the increment methods checks for its list before touching it. Leaving one out of a call
# to scrape_and_upload therefore raises nothing and logs nothing: the number simply stays at
# zero. That has already happened once per counter. assets_processed, cached_counter,
# locked_counter and failed_counter were each added to the bulk import from the Bulk Import
# tab and none of them reached the command line path, which was still passing only a
# success_counter years later. These two check that both paths fill in every counter the
# class declares, so the next one added cannot go quiet in one of them.

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
