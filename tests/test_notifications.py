"""
Unit tests for per-event, per-channel notification routing (issue #9).

Covers:
- Config migration of legacy bare-string apprise_urls into {"url", "events"} channels,
  conservative enough that an upgrade does not start sending more than before.
- normalize_notification_channels(), used both by Config.load() and by the web save route.
- utils.notifications.send_notification() only notifying channels subscribed to the given event.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

import core.globals as globals
from artwork_uploader import process_bulk_file_on_schedule, process_bulk_import_from_ui, run_bulk_import_scrape_in_thread
from core.config import Config, normalize_notification_channels
from core.constants import DEFAULT_NOTIFICATION_EVENTS
from core.enums import NotificationEvent
from models.instance import Instance
from utils.notifications import send_notification


# A run counts as scheduled when it carries a schedule id. The value itself is
# not read by anything under test here, only its presence.
SCHEDULE_ID = str(uuid.uuid4())


@pytest.mark.unit
def test_legacy_string_urls_migrate_to_default_events(tmp_path):
    """A pre-existing config.json with a bare list of URL strings must come back as
    channels subscribed to exactly the events that were sent before per-event routing
    existed: the started push and the completion or cancellation summary. The truly
    new events (failed to start, skipped) stay off - an upgrade must not send more
    kinds of notification than the user already received."""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"apprise_urls": ["discord://webhook1", "discord://webhook2"]}', encoding="utf-8"
    )

    config = Config(str(config_path))
    config.load()

    assert config.apprise_urls == [
        {"url": "discord://webhook1", "events": list(DEFAULT_NOTIFICATION_EVENTS)},
        {"url": "discord://webhook2", "events": list(DEFAULT_NOTIFICATION_EVENTS)},
    ]
    # The genuinely new events are not silently switched on for an upgraded channel.
    # run_started and run_cancelled ARE on: upstream sent both before per-event
    # routing existed, so keeping them matches what the user already received.
    assert NotificationEvent.RUN_FAILED_TO_START.value not in config.apprise_urls[0]["events"]
    assert NotificationEvent.RUN_SKIPPED.value not in config.apprise_urls[0]["events"]
    assert NotificationEvent.RUN_STARTED.value in config.apprise_urls[0]["events"]
    assert NotificationEvent.RUN_CANCELLED.value in config.apprise_urls[0]["events"]


@pytest.mark.unit
def test_channel_dicts_round_trip_through_load_and_save(tmp_path):
    """A config already in the new per-event shape keeps its exact event selection."""
    config_path = tmp_path / "config.json"
    config = Config(str(config_path))
    config.apprise_urls = [{"url": "discord://webhook1", "events": [NotificationEvent.RUN_CANCELLED.value]}]
    config.save()

    reloaded = Config(str(config_path))
    reloaded.load()

    assert reloaded.apprise_urls == [{"url": "discord://webhook1", "events": [NotificationEvent.RUN_CANCELLED.value]}]


@pytest.mark.unit
def test_normalize_notification_channels_drops_empty_urls():
    channels = normalize_notification_channels([
        {"url": "", "events": ["run_completed"]},
        {"url": "discord://webhook1", "events": ["run_completed"]},
        "",
        "discord://webhook2",
    ])

    assert channels == [
        {"url": "discord://webhook1", "events": ["run_completed"]},
        {"url": "discord://webhook2", "events": list(DEFAULT_NOTIFICATION_EVENTS)},
    ]


@pytest.mark.unit
def test_normalize_notification_channels_falls_back_on_a_non_list_events_value():
    """A hand-edited config.json with 'events' written as a bare string (missing the
    brackets) must not get silently split into one-character event names - that would
    make the channel match nothing forever with no obvious cause. Fall back to the
    conservative default instead."""
    channels = normalize_notification_channels([
        {"url": "discord://webhook1", "events": "run_completed"},
    ])

    assert channels == [
        {"url": "discord://webhook1", "events": list(DEFAULT_NOTIFICATION_EVENTS)},
    ]


@pytest.mark.unit
def test_send_notification_only_reaches_channels_subscribed_to_the_event():
    """A channel that only wants failures must stay silent on a clean completion,
    and vice versa - this is the whole point of per-event routing."""
    try:
        globals.config = MagicMock(apprise_urls=[
            {"url": "discord://failures-only", "events": [NotificationEvent.RUN_FAILED_TO_START.value]},
            {"url": "discord://everything", "events": [
                NotificationEvent.RUN_COMPLETED.value,
                NotificationEvent.RUN_FAILED_TO_START.value,
            ]},
        ])
        instance = Instance(mode="cli")

        with patch("utils.notifications.NotifyService") as mock_notify_service_cls:
            mock_notifier = MagicMock()
            mock_notifier.send_notification.return_value = True
            mock_notify_service_cls.return_value = mock_notifier

            send_notification(instance, "Run completed", event=NotificationEvent.RUN_COMPLETED.value)

        notified_urls = [call.args[0] for call in mock_notifier.add_url.call_args_list]
        assert notified_urls == ["discord://everything"]
    finally:
        globals.config = None


@pytest.mark.unit
def test_send_notification_skips_all_channels_when_none_are_subscribed():
    try:
        globals.config = MagicMock(apprise_urls=[
            {"url": "discord://completions-only", "events": [NotificationEvent.RUN_COMPLETED.value]},
        ])
        instance = Instance(mode="cli")

        with patch("utils.notifications.NotifyService") as mock_notify_service_cls:
            send_notification(instance, "Run was cancelled", event=NotificationEvent.RUN_CANCELLED.value)

        mock_notify_service_cls.assert_not_called()
    finally:
        globals.config = None


@pytest.mark.unit
def test_scheduled_run_with_missing_bulk_file_fires_failed_to_start():
    """The case the ticket cares about most: a scheduled run that never happens must
    still notify, using the run_failed_to_start event rather than staying silent."""
    events_sent = []

    def fake_send_notification(instance, message, event=None):
        events_sent.append(event)

    with (
        patch("artwork_uploader.find_bulk_file", return_value=None),
        patch("artwork_uploader.send_notification", side_effect=fake_send_notification),
        patch("artwork_uploader.update_log"),
    ):
        process_bulk_file_on_schedule(Instance(mode="cli"), "missing.txt", SCHEDULE_ID)

    assert events_sent == [NotificationEvent.RUN_FAILED_TO_START.value]


@pytest.mark.unit
def test_scheduled_run_with_empty_bulk_file_fires_skipped(tmp_path):
    """An empty scheduled bulk file is not an error - it should notify run_skipped,
    not run_failed_to_start, and must not attempt to start a scrape."""
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")

    events_sent = []

    def fake_send_notification(instance, message, event=None):
        events_sent.append(event)

    with (
        patch("artwork_uploader.find_bulk_file", return_value=str(empty_file)),
        patch("artwork_uploader.send_notification", side_effect=fake_send_notification),
        patch("artwork_uploader.update_log"),
        patch("artwork_uploader.run_bulk_import_scrape_in_thread") as mock_run,
    ):
        process_bulk_file_on_schedule(Instance(mode="cli"), "empty.txt", SCHEDULE_ID)

    assert events_sent == [NotificationEvent.RUN_SKIPPED.value]
    mock_run.assert_not_called()


@pytest.mark.unit
def test_manual_run_with_no_valid_entries_stays_silent_unless_notify_opted_in():
    """Manual runs must default to not notifying (today's behaviour) and only notify
    when the caller explicitly opts in via notify=True."""
    with (
        patch("artwork_uploader.send_notification") as mock_send_notification,
        patch("artwork_uploader.update_status"),
    ):
        run_bulk_import_scrape_in_thread(Instance(mode="cli"), "# just a comment\n", "bulk.txt", notify=False)
    mock_send_notification.assert_not_called()

    with (
        patch("artwork_uploader.send_notification") as mock_send_notification,
        patch("artwork_uploader.update_status"),
    ):
        run_bulk_import_scrape_in_thread(Instance(mode="cli"), "# just a comment\n", "bulk.txt", notify=True)
    mock_send_notification.assert_called_once()
    assert mock_send_notification.call_args.kwargs["event"] == NotificationEvent.RUN_SKIPPED.value
    # A manual run must not claim to be a scheduled one in the message it sends.
    notified_message = mock_send_notification.call_args.args[1]
    assert "Scheduled" not in notified_message


@pytest.mark.unit
def test_scheduled_run_with_no_valid_entries_keeps_scheduled_wording():
    """The scheduled counterpart of the manual-run test above: the message must say
    'Scheduled' here, since it genuinely was a scheduled run."""
    with (
        patch("artwork_uploader.send_notification") as mock_send_notification,
        patch("artwork_uploader.update_status"),
    ):
        run_bulk_import_scrape_in_thread(Instance(mode="cli"), "# just a comment\n", "bulk.txt", schedule_id=SCHEDULE_ID, notify=False)

    mock_send_notification.assert_called_once()
    assert mock_send_notification.call_args.kwargs["event"] == NotificationEvent.RUN_SKIPPED.value
    assert "Scheduled" in mock_send_notification.call_args.args[1]


@pytest.mark.unit
def test_clean_and_errored_completions_notify_different_events():
    """The completion branch must pick run_completed for a clean run and
    run_completed_with_errors when any URL errored - this is the ternary the whole
    per-event model hinges on for the common case."""
    try:
        globals.plex = MagicMock(tv_libraries=["TV Shows"], movie_libraries=["Movies"])
        globals.config = MagicMock(apprise_urls=[])
        globals.scrapes_running = 0
        globals.cancel_scrape = False
        instance = Instance(mode="cli")

        events_sent = []

        def fake_send_notification(inst, message, event=None):
            events_sent.append(event)

        # Clean run: scrape_and_upload never raises.
        with (
            patch("artwork_uploader.scrape_and_upload"),
            patch("artwork_uploader.send_notification", side_effect=fake_send_notification),
            patch("artwork_uploader.update_log"),
            patch("artwork_uploader.update_status"),
            patch("artwork_uploader.notify_web"),
            patch("artwork_uploader.debug_me"),
        ):
            process_bulk_import_from_ui(instance, [MagicMock()], "clean.txt", schedule_id=SCHEDULE_ID)

        assert events_sent == [NotificationEvent.RUN_COMPLETED.value]

        # Errored run: scrape_and_upload raises ScraperException for the one URL.
        events_sent.clear()
        from core.exceptions import ScraperException
        with (
            patch("artwork_uploader.scrape_and_upload", side_effect=ScraperException("boom")),
            patch("artwork_uploader.send_notification", side_effect=fake_send_notification),
            patch("artwork_uploader.update_log"),
            patch("artwork_uploader.update_status"),
            patch("artwork_uploader.notify_web"),
            patch("artwork_uploader.debug_me"),
        ):
            process_bulk_import_from_ui(instance, [MagicMock()], "errored.txt", schedule_id=SCHEDULE_ID)

        assert events_sent == [NotificationEvent.RUN_COMPLETED_WITH_ERRORS.value]
    finally:
        globals.plex = None
        globals.config = None
        globals.scrapes_running = 0
        globals.cancel_scrape = False


@pytest.mark.unit
def test_plex_setup_incomplete_notifies_failed_to_start_only_when_notify_enabled():
    """A run that can't even start because Plex isn't configured must still notify
    failed_to_start when notifications are enabled for it, and stay silent otherwise -
    this is the earliest exit point in the function, easy to forget when wiring events."""
    try:
        globals.plex = MagicMock(tv_libraries=None, movie_libraries=None)
        instance = Instance(mode="cli")

        with (
            patch("artwork_uploader.send_notification") as mock_send_notification,
            patch("artwork_uploader.update_status"),
        ):
            process_bulk_import_from_ui(instance, [MagicMock()], "test.txt", notify=False)
        mock_send_notification.assert_not_called()

        with (
            patch("artwork_uploader.send_notification") as mock_send_notification,
            patch("artwork_uploader.update_status"),
        ):
            process_bulk_import_from_ui(instance, [MagicMock()], "test.txt", schedule_id=SCHEDULE_ID, notify=False)
        mock_send_notification.assert_called_once_with(
            instance,
            "🔴 Bulk import of 'test.txt' failed to start • Plex setup incomplete",
            event=NotificationEvent.RUN_FAILED_TO_START.value,
        )
    finally:
        globals.plex = None


@pytest.mark.unit
def test_cancelled_run_notifies_run_cancelled_specifically():
    """Cancellation is one of the five named events - it must route as run_cancelled,
    not just fire *some* notification. Guards against it silently falling back to
    run_completed_with_errors or another event if the branch is refactored."""
    try:
        globals.plex = MagicMock(tv_libraries=["TV Shows"], movie_libraries=["Movies"])
        globals.config = MagicMock(apprise_urls=[])
        globals.scrapes_running = 0
        globals.cancel_scrape = True
        instance = Instance(mode="cli")

        with (
            patch("artwork_uploader.scrape_and_upload") as mock_scrape_and_upload,
            patch("artwork_uploader.send_notification") as mock_send_notification,
            patch("artwork_uploader.update_log"),
            patch("artwork_uploader.update_status"),
            patch("artwork_uploader.notify_web"),
            patch("artwork_uploader.debug_me"),
        ):
            process_bulk_import_from_ui(instance, [MagicMock()], "cancelled.txt", schedule_id=SCHEDULE_ID)

        mock_scrape_and_upload.assert_not_called()
        mock_send_notification.assert_called_once()
        assert mock_send_notification.call_args.kwargs["event"] == NotificationEvent.RUN_CANCELLED.value
    finally:
        globals.plex = None
        globals.config = None
        globals.scrapes_running = 0
        globals.cancel_scrape = False


@pytest.mark.unit
def test_mid_run_crash_after_processing_is_not_reported_as_failed_to_start():
    """scrape_and_upload only shields the loop from ScraperException - a
    PlexConnectorException or anything else it raises escapes the loop mid-run. If work
    had already happened (assets processed > 0), that must not be reported as
    run_failed_to_start: a channel subscribed only to failures-that-never-ran would be
    told a three-quarters-done run never started at all."""
    try:
        globals.plex = MagicMock(tv_libraries=["TV Shows"], movie_libraries=["Movies"])
        globals.config = MagicMock(apprise_urls=[])
        globals.scrapes_running = 0
        globals.cancel_scrape = False
        instance = Instance(mode="cli")

        from core.exceptions import PlexConnectorException

        call_count = {"n": 0}

        def flaky_scrape_and_upload(inst, url, options, bulk, tally=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                tally.assets(1)
                return
            raise PlexConnectorException("Plex connection dropped")

        with (
            patch("artwork_uploader.scrape_and_upload", side_effect=flaky_scrape_and_upload),
            patch("artwork_uploader.send_notification") as mock_send_notification,
            patch("artwork_uploader.update_log"),
            patch("artwork_uploader.update_status"),
            patch("artwork_uploader.notify_web"),
            patch("artwork_uploader.debug_me"),
        ):
            process_bulk_import_from_ui(instance, [MagicMock(), MagicMock()], "nightly.txt", schedule_id=SCHEDULE_ID)

        mock_send_notification.assert_called_once()
        assert mock_send_notification.call_args.kwargs["event"] == NotificationEvent.RUN_COMPLETED_WITH_ERRORS.value
        notified_message = mock_send_notification.call_args.args[1]
        assert "failed to start" not in notified_message
        assert "1 asset(s) processed" in notified_message
    finally:
        globals.plex = None
        globals.config = None
        globals.scrapes_running = 0
        globals.cancel_scrape = False


@pytest.mark.unit
def test_mid_run_crash_before_any_processing_is_reported_as_failed_to_start():
    """The counterpart of the test above: if the crash happens before anything was
    actually processed, run_failed_to_start is still the right event."""
    try:
        globals.plex = MagicMock(tv_libraries=["TV Shows"], movie_libraries=["Movies"])
        globals.config = MagicMock(apprise_urls=[])
        globals.scrapes_running = 0
        globals.cancel_scrape = False
        instance = Instance(mode="cli")

        from core.exceptions import PlexConnectorException

        with (
            patch("artwork_uploader.scrape_and_upload", side_effect=PlexConnectorException("Plex connection dropped")),
            patch("artwork_uploader.send_notification") as mock_send_notification,
            patch("artwork_uploader.update_log"),
            patch("artwork_uploader.update_status"),
            patch("artwork_uploader.notify_web"),
            patch("artwork_uploader.debug_me"),
        ):
            process_bulk_import_from_ui(instance, [MagicMock()], "nightly.txt", schedule_id=SCHEDULE_ID)

        mock_send_notification.assert_called_once()
        assert mock_send_notification.call_args.kwargs["event"] == NotificationEvent.RUN_FAILED_TO_START.value
    finally:
        globals.plex = None
        globals.config = None
        globals.scrapes_running = 0
        globals.cancel_scrape = False


@pytest.mark.unit
def test_an_upload_that_exhausted_its_retries_sends_completed_with_errors():
    """The summary line for such a run already reads "completed with 1 error(s)", but the
    event picked on the scrape errors alone, so a channel subscribed to failures heard
    nothing and a channel subscribed to clean runs got the warning."""
    try:
        globals.plex = MagicMock(tv_libraries=["TV Shows"], movie_libraries=["Movies"])
        globals.config = MagicMock(apprise_urls=[])
        globals.scrapes_running = 0
        globals.cancel_scrape = False

        events_sent = []

        def fake_send_notification(inst, message, event=None):
            events_sent.append(event)

        def fake_scrape(instance, url, options, bulk, tally=None):
            tally.assets(1)
            tally.failed(1)

        with (
            patch("artwork_uploader.scrape_and_upload", side_effect=fake_scrape),
            patch("artwork_uploader.send_notification", side_effect=fake_send_notification),
            patch("artwork_uploader.update_log"),
            patch("artwork_uploader.update_status"),
            patch("artwork_uploader.notify_web"),
            patch("artwork_uploader.debug_me"),
        ):
            process_bulk_import_from_ui(Instance(mode="cli"), [MagicMock()], "retries.txt", schedule_id=SCHEDULE_ID)

        assert events_sent == [NotificationEvent.RUN_COMPLETED_WITH_ERRORS.value]
    finally:
        globals.plex = None
        globals.config = None
        globals.scrapes_running = 0
        globals.cancel_scrape = False
