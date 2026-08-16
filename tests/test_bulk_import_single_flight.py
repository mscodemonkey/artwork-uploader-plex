"""
Tests for the bulk import single-flight guard.

Nothing used to stop two bulk imports running at the same time: two schedules
landing on the same minute, or a manual run started while a scheduled one is
still going, would both increment globals.scrapes_running and race each other
against the same Plex library. process_bulk_import_from_ui now takes
globals.bulk_import_lock before it does anything else and refuses (does not
queue) a second run while the lock is held.
"""

import threading
import uuid
from unittest.mock import MagicMock, patch

import pytest

import core.globals as globals
from artwork_uploader import process_bulk_import_from_ui
from models.instance import Instance


# A run counts as scheduled when it carries a schedule id. The value itself is
# not read by anything under test here, only its presence.
SCHEDULE_ID = str(uuid.uuid4())


@pytest.mark.unit
def test_second_bulk_import_is_refused_while_one_is_running():
    """A bulk import that starts while the lock is already held must not touch
    scrapes_running or scrape_and_upload - it is refused outright, not queued."""
    try:
        globals.bulk_import_lock.acquire()
        globals.scrapes_running = 0
        globals.cancel_scrape = False

        instance = Instance(mode="cli")
        parsed_urls = [MagicMock()]

        messages = {}

        def fake_update_log(inst, message, *args, **kwargs):
            messages["log"] = message

        def fake_update_status(inst, message, *args, **kwargs):
            messages["status"] = message

        with (
            patch("artwork_uploader.scrape_and_upload") as mock_scrape_and_upload,
            patch("artwork_uploader.update_log", side_effect=fake_update_log),
            patch("artwork_uploader.update_status", side_effect=fake_update_status),
            patch("artwork_uploader.send_notification") as mock_send_notification,
            patch("artwork_uploader.notify_web"),
            patch("artwork_uploader.debug_me"),
        ):
            process_bulk_import_from_ui(instance, parsed_urls, "test_bulk.txt")

        mock_scrape_and_upload.assert_not_called()
        mock_send_notification.assert_not_called()  # not scheduled, so no notification is sent
        assert globals.scrapes_running == 0, "a refused run must never increment scrapes_running"

        assert "log" in messages
        assert "refused" in messages["log"].lower()
        assert "already running" in messages["log"].lower()

        assert "status" in messages
        assert "refused" in messages["status"].lower()
    finally:
        if globals.bulk_import_lock.locked():
            globals.bulk_import_lock.release()
        globals.cancel_scrape = False
        globals.scrapes_running = 0


@pytest.mark.unit
def test_refused_scheduled_bulk_import_sends_a_notification():
    """A scheduled run that is refused must still tell the notification services,
    or the collision is invisible to whoever isn't watching the web UI at the time."""
    try:
        globals.bulk_import_lock.acquire()
        globals.scrapes_running = 0
        globals.cancel_scrape = False

        instance = Instance(mode="cli")
        parsed_urls = [MagicMock()]

        with (
            patch("artwork_uploader.scrape_and_upload") as mock_scrape_and_upload,
            patch("artwork_uploader.update_log"),
            patch("artwork_uploader.update_status"),
            patch("artwork_uploader.send_notification") as mock_send_notification,
            patch("artwork_uploader.notify_web"),
            patch("artwork_uploader.debug_me"),
        ):
            process_bulk_import_from_ui(instance, parsed_urls, "test_bulk.txt", schedule_id=SCHEDULE_ID)

        mock_scrape_and_upload.assert_not_called()
        mock_send_notification.assert_called_once()
        assert "refused" in mock_send_notification.call_args.args[1].lower()
    finally:
        if globals.bulk_import_lock.locked():
            globals.bulk_import_lock.release()
        globals.cancel_scrape = False
        globals.scrapes_running = 0


@pytest.mark.unit
def test_bulk_import_releases_the_lock_so_the_next_run_can_start():
    """A completed bulk import must release globals.bulk_import_lock, otherwise every
    run after the first would be refused forever."""
    try:
        globals.bulk_import_lock = type(globals.bulk_import_lock)()  # fresh, unlocked lock
        globals.scrapes_running = 0
        globals.cancel_scrape = False
        globals.plex = MagicMock(tv_libraries=MagicMock(), movie_libraries=MagicMock())
        globals.config = MagicMock(apprise_urls=[])

        instance = Instance(mode="cli")
        parsed_urls = [MagicMock()]

        with (
            patch("artwork_uploader.scrape_and_upload") as mock_scrape_and_upload,
            patch("artwork_uploader.update_log"),
            patch("artwork_uploader.update_status"),
            patch("artwork_uploader.send_notification"),
            patch("artwork_uploader.notify_web"),
            patch("artwork_uploader.debug_me"),
        ):
            process_bulk_import_from_ui(instance, parsed_urls, "test_bulk.txt")

        mock_scrape_and_upload.assert_called_once()
        assert not globals.bulk_import_lock.locked(), "the lock must be released once the run ends"
        assert globals.scrapes_running == 0
    finally:
        if globals.bulk_import_lock.locked():
            globals.bulk_import_lock.release()
        globals.cancel_scrape = False
        globals.scrapes_running = 0
        globals.plex = None
        globals.config = None


@pytest.mark.unit
def test_bulk_import_releases_the_lock_when_plex_is_not_configured():
    """The Plex-incomplete early return sits inside the same try/finally as the rest of the
    run, before scrapes_running is even incremented - a state a scheduled run can easily hit
    if Plex is unreachable. It must still release the lock, or a single misconfigured run
    would permanently jam every bulk import after it."""
    try:
        globals.bulk_import_lock = type(globals.bulk_import_lock)()  # fresh, unlocked lock
        globals.scrapes_running = 0
        globals.cancel_scrape = False
        globals.plex = MagicMock(tv_libraries=None, movie_libraries=None)

        instance = Instance(mode="cli")
        parsed_urls = [MagicMock()]

        with (
            patch("artwork_uploader.scrape_and_upload") as mock_scrape_and_upload,
            patch("artwork_uploader.update_log"),
            patch("artwork_uploader.update_status") as mock_update_status,
            patch("artwork_uploader.send_notification"),
            patch("artwork_uploader.notify_web"),
            patch("artwork_uploader.debug_me"),
        ):
            process_bulk_import_from_ui(instance, parsed_urls, "test_bulk.txt")

        mock_scrape_and_upload.assert_not_called()
        mock_update_status.assert_called_once()
        assert "Plex setup incomplete" in mock_update_status.call_args.args[1]
        assert not globals.bulk_import_lock.locked(), "the lock must be released even when Plex isn't configured"
        assert globals.scrapes_running == 0
    finally:
        if globals.bulk_import_lock.locked():
            globals.bulk_import_lock.release()
        globals.cancel_scrape = False
        globals.scrapes_running = 0
        globals.plex = None


@pytest.mark.unit
def test_lock_actually_serializes_concurrent_bulk_imports():
    """Exercise the lock under real thread concurrency rather than a pre-armed lock. A plain
    'check scrapes_running, then increment it' guard has a window between the check and the
    increment where two threads can both pass the check - that is the exact bug this ticket
    is about, and a test that only pre-locks before calling would not catch it coming back."""
    try:
        globals.bulk_import_lock = type(globals.bulk_import_lock)()  # fresh, unlocked lock
        globals.scrapes_running = 0
        globals.cancel_scrape = False
        globals.plex = MagicMock(tv_libraries=MagicMock(), movie_libraries=MagicMock())
        globals.config = MagicMock(apprise_urls=[])

        first_entered = threading.Event()
        release_first = threading.Event()
        calls = []

        def slow_scrape_and_upload(*args, **kwargs):
            calls.append("scrape")
            first_entered.set()
            release_first.wait(timeout=5)
            return None

        with (
            patch("artwork_uploader.scrape_and_upload", side_effect=slow_scrape_and_upload),
            patch("artwork_uploader.update_log"),
            patch("artwork_uploader.update_status"),
            patch("artwork_uploader.send_notification"),
            patch("artwork_uploader.notify_web"),
            patch("artwork_uploader.debug_me"),
        ):
            first_thread = threading.Thread(
                target=process_bulk_import_from_ui,
                args=(Instance(mode="cli"), [MagicMock()], "first.txt"),
            )
            first_thread.start()
            assert first_entered.wait(timeout=5), "first run never reached scrape_and_upload"

            # The second run starts on this thread while the first is still inside its
            # critical section on the other thread - this is the actual race the ticket
            # describes (two schedules landing together, or a manual run overlapping a
            # scheduled one).
            process_bulk_import_from_ui(Instance(mode="cli"), [MagicMock()], "second.txt")

            release_first.set()
            first_thread.join(timeout=5)

        assert calls == ["scrape"], "the second run must not have called scrape_and_upload while the first was in flight"
    finally:
        if globals.bulk_import_lock.locked():
            globals.bulk_import_lock.release()
        globals.cancel_scrape = False
        globals.scrapes_running = 0
        globals.plex = None
        globals.config = None
