"""Unit tests for the run-summary counters."""

import pytest

from models.callbacks import ProcessingCallbacks
from services.artwork_processor import ArtworkProcessor


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
