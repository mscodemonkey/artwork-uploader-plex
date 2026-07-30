"""Unit tests for the bulk-import run-summary counters."""

from models.callbacks import ProcessingCallbacks
from services.artwork_processor import ArtworkProcessor


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
