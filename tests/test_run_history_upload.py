"""
Covers the run history record process_uploaded_artwork writes.

Artwork uploaded as a ZIP goes to Plex through the same uploader a scrape uses, so it
leaves the same kind of record. There is no cache crawl behind an upload, so the cached
count on one of these rows is always zero.
"""

from unittest.mock import MagicMock, patch

import pytest

import core.globals as globals
from artwork_uploader import process_uploaded_artwork
from models.instance import Instance
from services.run_history import RunHistory
from core.enums import RunType, RunTrigger, RunOutcome

OUTCOME_SUCCESS = RunOutcome.SUCCESS.value
OUTCOME_PARTIAL = RunOutcome.PARTIAL.value
OUTCOME_STOPPED = RunOutcome.STOPPED.value
OUTCOME_FAILED = RunOutcome.FAILED.value
OUTCOME_SKIPPED = RunOutcome.SKIPPED.value
RUN_TYPE_UPLOAD = RunType.UPLOAD.value
TRIGGER_MANUAL = RunTrigger.MANUAL.value



@pytest.fixture
def history(tmp_path, monkeypatch):
    real_history = RunHistory(str(tmp_path / "run_history.json"))
    monkeypatch.setattr("artwork_uploader.RunHistory", lambda: real_history)
    return real_history


@pytest.fixture(autouse=True)
def reset_globals():
    globals.plex = MagicMock()
    globals.config = MagicMock(apprise_urls=[])
    try:
        yield
    finally:
        globals.cancel_scrape = False
        globals.scrapes_running = 0
        globals.plex = None
        globals.config = None


def _processor(**counts):
    """An ArtworkProcessor stand-in that moves the counters it was handed."""
    class _FakeProcessor:
        def __init__(self, _plex, callbacks):
            self.callbacks = callbacks

        def process_uploaded_files(self, *args, **kwargs):
            for name, count in counts.items():
                getattr(self.callbacks, name)(count)
    return _FakeProcessor


def _upload(instance_mode="cli", title="A Set"):
    process_uploaded_artwork(
        Instance(mode=instance_mode), [MagicMock()], 0, title, "someone", "theposterdb", [], []
    )


@pytest.mark.unit
def test_an_upload_is_recorded_with_its_counters(history):
    with (
        patch("artwork_uploader.ArtworkProcessor", _processor(assets=4, success=3, locked=1)),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
        patch("artwork_uploader.update_log"),
    ):
        _upload()

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["run_type"] == RUN_TYPE_UPLOAD
    assert runs[0]["trigger"] == TRIGGER_MANUAL
    assert runs[0]["label"] == "A Set"
    assert runs[0]["outcome"] == OUTCOME_SUCCESS
    assert runs[0]["assets_processed"] == 4
    assert runs[0]["success_count"] == 3
    assert runs[0]["locked_count"] == 1
    assert runs[0]["cached_count"] == 0


@pytest.mark.unit
def test_an_upload_with_failed_assets_is_recorded_as_partial(history):
    with (
        patch("artwork_uploader.ArtworkProcessor", _processor(assets=2, success=1, failed=1)),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
        patch("artwork_uploader.update_log"),
    ):
        _upload()

    runs = history.get_runs()
    assert runs[0]["outcome"] == OUTCOME_PARTIAL
    assert runs[0]["error_count"] == 1


@pytest.mark.unit
def test_an_upload_that_processed_nothing_is_recorded_as_skipped(history):
    with (
        patch("artwork_uploader.ArtworkProcessor", _processor()),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
        patch("artwork_uploader.update_log"),
    ):
        _upload()

    assert history.get_runs()[0]["outcome"] == OUTCOME_SKIPPED


@pytest.mark.unit
def test_a_cancelled_upload_is_recorded_as_stopped(history):
    class _CancellingProcessor:
        def __init__(self, _plex, callbacks):
            self.callbacks = callbacks

        def process_uploaded_files(self, *args, **kwargs):
            self.callbacks.assets(1)
            globals.cancel_scrape = True

    with (
        patch("artwork_uploader.ArtworkProcessor", _CancellingProcessor),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
        patch("artwork_uploader.update_log"),
    ):
        _upload()

    assert history.get_runs()[0]["outcome"] == OUTCOME_STOPPED


@pytest.mark.unit
def test_an_upload_that_raised_is_recorded_as_failed(history):
    class _ExplodingProcessor:
        def __init__(self, _plex, callbacks):
            pass

        def process_uploaded_files(self, *args, **kwargs):
            raise RuntimeError("boom")

    with (
        patch("artwork_uploader.ArtworkProcessor", _ExplodingProcessor),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
        patch("artwork_uploader.update_log"),
        pytest.raises(RuntimeError),
    ):
        _upload()

    assert history.get_runs()[0]["outcome"] == OUTCOME_FAILED


@pytest.mark.unit
def test_an_untitled_zip_still_gets_a_label(history):
    """A ZIP with no title must not land in the table as an empty cell."""
    with (
        patch("artwork_uploader.ArtworkProcessor", _processor(assets=1, success=1)),
        patch("artwork_uploader.notify_web"),
        patch("artwork_uploader.update_status"),
        patch("artwork_uploader.update_log"),
    ):
        _upload(title=None)

    assert history.get_runs()[0]["label"] == "Uploaded artwork"
