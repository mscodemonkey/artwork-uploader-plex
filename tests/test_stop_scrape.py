"""
Tests for the scrape-cancellation "Stop" plumbing.

Covers request_scrape_stop(): it must only arm globals.cancel_scrape when a scrape
is actually in flight, so a stale Stop click can't leak forward and cancel the
next run before it starts.

Also covers the P1+P2 break checks: once cancel_scrape is armed, the TPDb crawl
loop and ArtworkProcessor's upload loops must both stop, rather than letting a
partial harvest reach Plex.
"""

from unittest.mock import MagicMock, patch

import pytest

import core.globals as globals
from artwork_uploader import process_bulk_import_from_ui, request_scrape_stop
from models.instance import Instance
from models.options import Options
from scrapers.theposterdb_scraper import ThePosterDBScraper
from services.artwork_processor import ArtworkProcessor
from models.callbacks import ProcessingCallbacks


@pytest.mark.unit
def test_stale_stop_cannot_arm_next_run():
    try:
        # Nothing running: Stop must be a no-op, not arm cancel_scrape for later.
        globals.scrapes_running = 0
        globals.cancel_scrape = False
        assert request_scrape_stop() is False
        assert globals.cancel_scrape is False

        # A scrape is in flight: Stop must arm cancel_scrape.
        globals.scrapes_running = 1
        assert request_scrape_stop() is True
        assert globals.cancel_scrape is True
    finally:
        globals.cancel_scrape = False
        globals.scrapes_running = 0


@pytest.mark.unit
def test_cancel_scrape_breaks_crawl_and_blocks_partial_upload():
    """
    P1+P2 must land together: breaking only the TPDb crawl loop would let scrape()
    return normally with a partial harvest that then gets uploaded to live Plex.
    This asserts both halves - the crawl stops early AND the partial harvest it
    collected is never handed to the upload processor.
    """
    try:
        # --- the TPDb user-page crawl loop breaks early on cancel_scrape ---
        globals.cancel_scrape = False
        with patch("core.config.Config.load", lambda self: None):
            scraper = ThePosterDBScraper(url="https://theposterdb.com/user/someuser", callbacks=ProcessingCallbacks(success_counter=[0]))
        scraper.user_pages = 5  # high page count; loop must not run to completion

        calls = {"n": 0}

        def fake_scrape_user_page(page):
            calls["n"] += 1
            if calls["n"] == 2:
                globals.cancel_scrape = True

        with (
            patch("utils.soup_utils.cook_soup", return_value=MagicMock()),
            patch.object(scraper, "scrape_user_info", lambda: None),
            patch.object(scraper, "scrape_user_page", side_effect=fake_scrape_user_page) as mock_scrape_page,
        ):
            scraper.scrape()

        assert mock_scrape_page.call_count < scraper.user_pages, "crawl loop should have broken early on cancel_scrape"

        # --- the per-artwork upload loops refuse to upload a cancelled harvest ---
        globals.cancel_scrape = True

        mock_scraper = MagicMock()
        mock_scraper.source = "theposterdb"
        mock_scraper.title = "Some Title"
        mock_scraper.author = "Some Author"
        mock_scraper.total = 3
        mock_scraper.skipped = 0
        mock_scraper.errored = 0
        mock_scraper.collection_artwork = [{"title": "Collection 1"}]
        mock_scraper.movie_artwork = [{"title": "Movie 1"}]
        mock_scraper.tv_artwork = [{"title": "Show 1"}]

        mock_upload_processor = MagicMock()
        mock_upload_processor.process_collection_artwork.return_value = []
        mock_upload_processor.process_movie_artwork.return_value = []
        mock_upload_processor.process_tv_artwork.return_value = []

        processor = ArtworkProcessor(plex=MagicMock(), callbacks=ProcessingCallbacks(success_counter=[0]))

        with (
            patch("services.artwork_processor.Scraper", return_value=mock_scraper),
            patch("services.artwork_processor.UploadProcessor", return_value=mock_upload_processor),
        ):
            processor.scrape_and_process(url="https://theposterdb.com/user/someuser", bulk=False, options=Options())

        mock_upload_processor.process_collection_artwork.assert_not_called()
        mock_upload_processor.process_movie_artwork.assert_not_called()
        mock_upload_processor.process_tv_artwork.assert_not_called()
    finally:
        globals.cancel_scrape = False
        globals.scrapes_running = 0


@pytest.mark.unit
def test_cancelled_bulk_run_reports_stopped_not_success():
    """
    P3: once cancel_scrape is armed, the bulk summary must report an honest
    "stopped" message - never the green "completed successfully" wording a
    finished run gets. This drives the real process_bulk_import_from_ui
    reporting branch (with the Plex-config check and the actual scrape
    stubbed out) so the assertions exercise real branch logic on
    globals.cancel_scrape, not a mock of it. scheduled=True so the
    notification branch runs too - a suppressed notification on a cancelled
    scheduled run would leave a dangling "started" with no terminal event.
    """
    try:
        globals.cancel_scrape = True
        globals.scrapes_running = 0
        globals.plex = MagicMock(tv_libraries=MagicMock(), movie_libraries=MagicMock())
        globals.config = MagicMock(apprise_urls=[])

        instance = Instance(mode="cli")
        parsed_urls = [MagicMock()]  # loop must break before this is ever touched

        messages = {}

        def fake_update_log(inst, message, *args, **kwargs):
            messages["log"] = message

        def fake_update_status(inst, message, *args, **kwargs):
            messages["status"] = message

        def fake_send_notification(inst, message, *args, **kwargs):
            messages["notification"] = message

        with (
            patch("artwork_uploader.scrape_and_upload") as mock_scrape_and_upload,
            patch("artwork_uploader.update_log", side_effect=fake_update_log),
            patch("artwork_uploader.update_status", side_effect=fake_update_status),
            patch("artwork_uploader.send_notification", side_effect=fake_send_notification),
            patch("artwork_uploader.notify_web") as mock_notify_web,
            patch("artwork_uploader.debug_me"),
        ):
            process_bulk_import_from_ui(instance, parsed_urls, "test_bulk.txt", scheduled=True)

        mock_scrape_and_upload.assert_not_called()

        assert "log" in messages, "update_log must fire even on a cancelled run"
        assert "🛑" in messages["log"]
        assert "stopped" in messages["log"].lower()
        assert "completed successfully" not in messages["log"]
        assert "Processed all artwork" not in messages["log"]

        assert "status" in messages
        assert "stopped" in messages["status"].lower()
        assert "completed successfully" not in messages["status"]
        assert "Processed all artwork" not in messages["status"]

        assert "notification" in messages, "a scheduled cancelled run must not suppress the terminal notification"
        assert "🛑" in messages["notification"]
        assert "completed successfully" not in messages["notification"]

        progress_hides = [
            c for c in mock_notify_web.call_args_list
            if len(c.args) >= 3 and c.args[1] == "progress_bar" and c.args[2].get("percent") == 100
        ]
        assert progress_hides, "a cancelled bulk run must clear the progress bar (emit percent 100)"
    finally:
        globals.cancel_scrape = False
        globals.scrapes_running = 0
        globals.plex = None
        globals.config = None


@pytest.mark.unit
def test_single_url_cancel_emits_stopped_status():
    """A cancelled single-URL scrape must surface a 'Stopped' status toast (color warning),
    not a green 'Processed all artwork' success - matching the bulk path's stopped feedback."""
    try:
        globals.cancel_scrape = True

        statuses = []

        callbacks = ProcessingCallbacks(
            success_counter=[0],
            on_status_update=lambda message, color, spinner, sticky: statuses.append((message, color)),
        )

        mock_scraper = MagicMock()
        mock_scraper.source = "theposterdb"
        mock_scraper.title = "Some Title"
        mock_scraper.author = "Some Author"
        mock_scraper.total = 3
        mock_scraper.skipped = 0
        mock_scraper.errored = 0
        mock_scraper.collection_artwork = []
        mock_scraper.movie_artwork = [{"title": "Movie 1"}]
        mock_scraper.tv_artwork = []

        processor = ArtworkProcessor(plex=MagicMock(), callbacks=callbacks)

        with (
            patch("services.artwork_processor.Scraper", return_value=mock_scraper),
            patch("services.artwork_processor.UploadProcessor", return_value=MagicMock()),
        ):
            processor.scrape_and_process(url="https://theposterdb.com/set/123", bulk=False, options=Options())

        assert statuses, "a cancelled single-URL scrape must emit a status toast"
        message, color = statuses[-1]
        assert "Stopped" in message
        assert "Processed all artwork" not in message
        assert color == "warning"
    finally:
        globals.cancel_scrape = False
        globals.scrapes_running = 0
