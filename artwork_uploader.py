import uuid, os, re, threading, sys, time
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from core import globals

# plexapi builds its X-Plex-Client-Identifier from uuid.getnode(), which can be
# random on every process start (commonly in Docker, where no MAC is readable).
# That registers each run as a brand new Plex device and fires new device
# notifications. Persist one identifier in the config folder and pass it to
# plexapi through its environment override, before plexapi is imported below.
# An identifier already set in the environment always takes precedence.
def _ensure_stable_plex_identifier() -> None:
    if os.environ.get("PLEXAPI_HEADER_IDENTIFIER"):
        return
    id_file = os.path.join("config", ".plex_client_id")
    try:
        if os.path.isfile(id_file):
            with open(id_file) as f:
                client_id = f.read().strip()
        else:
            client_id = str(uuid.uuid4())
            os.makedirs("config", exist_ok=True)
            with open(id_file, "w") as f:
                f.write(client_id)
        if client_id:
            os.environ["PLEXAPI_HEADER_IDENTIFIER"] = client_id
            os.environ.setdefault("PLEXAPI_HEADER_DEVICE_NAME", "Artwork Uploader")
    except OSError:
        pass  # fall back to the plexapi default rather than block startup

_ensure_stable_plex_identifier()

from models import arguments
from models.instance import Instance
from utils.notifications import update_log, update_status, notify_web, debug_me, send_notification
from core.config import Config
from core.exceptions import ConfigLoadError, PlexConnectorException, ScraperException, InvalidUrl, InvalidFlag
from utils.utils import is_not_comment, parse_url_and_options, elapsed_time
from models.options import Options
from plex.plex_connector import PlexConnector
from core.constants import (
    CURRENT_VERSION,
    GITHUB_REPO,
    DEFAULT_WEB_PORT,
    DEFAULT_WEB_HOST,
    SCHEDULER_CHECK_INTERVAL,
    UPDATE_CHECK_INTERVAL,
    MIN_PYTHON_MAJOR,
    MIN_PYTHON_MINOR,
    VALID_FILENAME_PATTERN
)
from core.enums import InstanceMode, NotificationEvent, StatusColor, RunType, RunTrigger, RunOutcome
from services import (
    BulkFileService,
    ImageService,
    WebhookService,
    UtilityService,
    RunHistory
)
from services.artwork_processor import ArtworkProcessor
from services.scheduler_service import SchedulerService, BulkSchedule
from models.callbacks import ProcessingCallbacks
from services.update_service import UpdateService


# ----------------------------------------------
# Important for autoupdater
current_version = CURRENT_VERSION
github_repo = GITHUB_REPO  
# ----------------------------------------------

if sys.version_info[0] != MIN_PYTHON_MAJOR or sys.version_info[1] < MIN_PYTHON_MINOR:
    print(f"Version: {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]} is not compatible with Artwork Uploader, please upgrade to Python {MIN_PYTHON_MAJOR}.{MIN_PYTHON_MINOR}+")
    sys.exit(0)

try:
    from flask import Flask, render_template
    from flask_socketio import SocketIO
except (ModuleNotFoundError, ImportError) as e:
    print("=" * 70)
    print("ERROR: Required dependencies are missing or incompatible")
    print("=" * 70)
    print(f"\nDetails: {str(e)}")
    print("\nThis usually means one of the following:")
    print("  1. Requirements not installed: Run 'pip install -r requirements.txt'")
    print("  2. Wrong Python version: Requires Python 3.10+")
    print("  3. Architecture mismatch (Apple Silicon): Reinstall dependencies")
    print("\nFor architecture issues on Apple Silicon Macs:")
    print("  pip uninstall Pillow Flask flask-socketio -y")
    print("  pip install Pillow Flask flask-socketio")
    print("\nOr use a virtual environment:")
    print("  python3 -m venv .venv")
    print("  source .venv/bin/activate")
    print("  pip install -r requirements.txt")
    print("\nSee README.md for more troubleshooting help.")
    print("=" * 70)
    sys.exit(1)

globals.docker = os.getenv("RUNNING_IN_DOCKER") == "1"


# ! Interactive CLI mode flag
interactive_cli = False  # Set to False when building the executable with PyInstaller for it launches the web UI by default
mode = InstanceMode.CLI.value
# Services moved to core.globals for proper cross-module access
config = None  # Initialized in main



# ---------------------- CORE FUNCTIONS ----------------------

def parse_bulk_file_from_cli(instance: Instance, file_path):

    """
    Load and parse the URLs from a bulk import file, then scrape them with any options set for that URL.
    """

    display_filename = os.path.basename(file_path)

    # A bulk import started from the command line is a run like any other, so it keeps the same
    # counters as one started from the Bulk Import tab and gets the same record in the history.
    # The outcome starts as failed: every path out of here is recorded, including one that
    # raises, and only a run that finished gets to say otherwise.
    started_at = datetime.now(timezone.utc).isoformat()
    outcome = RunOutcome.FAILED.value
    tally = ProcessingCallbacks()
    errors = 0

    # Open the file and read the contents
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            urls = file.readlines()
    except FileNotFoundError:
        print("File not found. Please enter a valid file path.")
        now = datetime.now(timezone.utc).isoformat()
        RunHistory().add_run(
            run_type=RunType.BULK.value,
            label=display_filename,
            started_at=started_at,
            ended_at=now,
            trigger=RunTrigger.CLI.value,
            outcome=RunOutcome.FAILED.value
        )
        return

    start_time = time.time()
    update_log(instance, f"🎬 Bulk process started for '{display_filename}'")

    try:

        # Loop through the file, process the URL and options, then scrape according to the URL
        for n, line in enumerate(urls, 1):

            # Skip comments
            if is_not_comment(line):

                # Parse the line to extract the URL and options
                try:
                    parsed_url = parse_url_and_options(line)
                except InvalidUrl as e:
                    update_log(instance, f"❌ Invalid URL found in bulk import file '{display_filename}', line {n}: '{str(e)}'")
                    errors += 1
                    continue
                except InvalidFlag as e:
                    update_log(instance, f"❌ One or more invalid flags found in bulk import file '{display_filename}', line {n}: {str(e)}")
                    errors += 1
                    continue

                try:
                    scrape_and_upload(
                        instance=instance,
                        url=parsed_url.url,
                        options=parsed_url.options,
                        tally=tally
                    )
                except ScraperException as e:
                    debug_me(f"ScraperException: Error processing {parsed_url.url}: {str(e)}")
                    errors += 1
                except Exception as e:
                    debug_me(f"Unknown Exception: Error processing {parsed_url.url}: {str(e)}")
                    errors += 1

        end_time = time.time()
        elapsed = elapsed_time(end_time - start_time)
        update_log(instance, f"🏁 Bulk process completed in {elapsed} for '{display_filename}'")

        # A line that failed to scrape at all is an error the uploader never saw, so it is
        # handed to the tally rather than counted twice. There is no Stop button behind a
        # command line run, so it can never end up stopped.
        outcome = tally.outcome(extra_errors=errors)

    finally:
        RunHistory().add_run(
            RunType.BULK.value, display_filename, started_at, datetime.now(timezone.utc).isoformat(),
            RunTrigger.CLI.value, outcome,
            tally.assets_processed[0], tally.success_counter[0], tally.cached_counter[0],
            tally.locked_counter[0], tally.errors(errors)
        )

# ---------------------- GUI FUNCTIONS ----------------------

# * UI helper functions ---

def get_exe_dir():
    """Get the directory of the executable or script file."""
    return UtilityService.get_exe_dir()


def request_scrape_stop() -> bool:
    """Ask any in-flight scrape to stop. Returns True if a run was flagged to stop, or
    False when nothing is running - a stale click must not arm the next run."""
    if globals.scrapes_running:
        globals.cancel_scrape = True
        return True
    return False


def process_scrape_url_from_web(instance: Instance, url: str) -> None:

    """
    Process the URL and any options, then scrape for posters and updates the GUI with the results
    Now switches to the session log tab when you hit the button so that you can see the results as they happen

    Args:
        instance:
        url: The URL to scrape.  Note that due to options, this may not be the only URL that we end up scraping!
    """

    title = None

    # A single scrape is a run like any other, so it gets the same counters a bulk import
    # keeps and the same record in the history. The outcome starts as failed: every path
    # out of here is recorded, including one that raises, and only a scrape that finished
    # gets to say otherwise.
    started_at = datetime.now(timezone.utc).isoformat()
    label = url
    outcome = RunOutcome.FAILED.value
    tally = ProcessingCallbacks()

    try:
        # Stop a run that has no Plex libraries, resolving them first if we're holding none
        if not globals.plex.ensure_libraries():
            update_status(instance, "Plex setup incomplete. Please configure your settings.", color=StatusColor.WARNING.value)
            return

        globals.scrapes_running += 1
        globals.scrape_type = "scrape"
        notify_web(instance, "scrape_state", { "running": True, "type": globals.scrape_type })

        # Process the URL and options passed from the GUI or website
        parsed_line = parse_url_and_options(url)
        label = parsed_line.url
        update_status(instance, f"Scraping URL '{parsed_line.url}'", color=StatusColor.INFO.value, sticky=True, spinner=True)

        title, author = scrape_and_upload(
            instance=instance,
            url=parsed_line.url,
            options=parsed_line.options,
            tally=tally
        )

        # Read the cancel flag here, not in the finally below - that's where it gets cleared
        outcome = tally.outcome(stopped=globals.cancel_scrape)

        # Update the web ui bulk list with this URL and artwork (only if it's not already in the bulk list)
        if instance.mode == "web" and parsed_line.options.add_to_bulk and title:
            notify_web(instance, "add_to_bulk_list", {"url": url, "title": title, "author": author})

    except ScraperException as scraping_error:
        update_status(instance, f"{scraping_error}", color=StatusColor.DANGER.value)

    finally:
        # Record before the scrape_state broadcast below, not after: that broadcast is what
        # makes the browser reload the history table, so a record written afterwards would
        # miss its own refresh and only appear the next time somebody opened the tab.
        RunHistory().add_run(
            RunType.SCRAPE.value, label, started_at, datetime.now(timezone.utc).isoformat(),
            RunTrigger.MANUAL.value, outcome,
            tally.assets_processed[0], tally.success_counter[0], tally.cached_counter[0],
            tally.locked_counter[0], tally.errors()
        )
        globals.scrapes_running -= 1
        if globals.scrapes_running <= 0:
            globals.scrapes_running = 0
            globals.cancel_scrape = False
            notify_web(instance, "scrape_state", { "running": False, "type": globals.scrape_type })
            globals.scrape_type = "stopped"

def run_bulk_import_scrape_in_thread(
        instance: Instance,
        web_list = None,
        filename = None,
        schedule_id: str = None,
        notify: bool = False
    ) -> None:

    """Run the bulk import scrape in a separate thread."""

    parsed_urls = []

    # Grab the one from the web interface
    bulk_import_list = web_list.strip().split("\n")

    # Loop through the import file and build a list of URLs and options
    # Ignoring any lines containing comments using # or //
    update_log(instance, f"🎬 Bulk process started for '{filename}'")

    for n, line in enumerate(bulk_import_list, 1):
        if is_not_comment(line):
            try:
                parsed_url = parse_url_and_options(line)
                parsed_urls.append(parsed_url)
            except InvalidUrl as e:
                update_log(instance, f"❌ Invalid URL found in bulk import file '{filename}', line {n}: '{str(e)}'")
                continue
            except InvalidFlag as e:
                update_log(instance, f"❌ One or more invalid flags found in bulk import file '{filename}', line {n}: {str(e)}")
                continue
    if len(parsed_urls) == 0:
        update_status(instance, "No valid bulk import entries found. Check logs for details", color=StatusColor.DANGER.value, icon="x-circle")
        now = datetime.now(timezone.utc).isoformat()
        if schedule_id:
            record_schedule_run(schedule_id)
        RunHistory().add_run(
            run_type=RunType.BULK.value,
            label=filename if filename else "bulk_import.txt",
            started_at=now,
            ended_at=now,
            trigger=RunTrigger.SCHEDULED.value if schedule_id else RunTrigger.MANUAL.value,
            outcome=RunOutcome.SKIPPED.value,
            job_id=schedule_id
        )
        if schedule_id or notify:
            prefix = "Scheduled b" if schedule_id else "B"
            display_filename = filename if filename else "bulk_import.txt"
            send_notification(instance, f"⏭️ {prefix}ulk import of '{display_filename}' skipped • no valid entries found", event=NotificationEvent.RUN_SKIPPED.value)
        return

    # Pass the processing of the parsed URLs off to a thread
    try:
        process_bulk_import_from_ui(
            instance=instance,
            parsed_urls=parsed_urls,
            filename=filename,
            schedule_id=schedule_id,
            notify=notify
        )
    except Exception:
        raise


def process_bulk_import_from_ui(
        instance: Instance,
        parsed_urls: list,
        filename: str = None,
        schedule_id: str = None,
        notify: bool = False
    ) -> None:

    """
    Process the bulk import scrape, based on the contents of the Bulk Import tab in the GUI.

    The bulk import list doesn't need to have been saved, it will use the list as it exists in the GUI currently.

    Args:
        instance:
        parsed_urls:    The URLs to scrape.  These can be theposterdb poster, set or user URL or a mediux set URL.
        filename:       The filename of the bulk import file being processed.
    """

    display_filename = filename if filename else "bulk_import.txt"

    # Single-flight guard: two bulk imports racing against the same Plex library is worse than
    # a skipped one - the artwork ID label and locked-field logic both assume a single writer.
    # A second run is refused rather than queued, so it doesn't silently pile up if schedules
    # collide repeatedly; the caller (a schedule or the user) simply tries again later.
    if not globals.bulk_import_lock.acquire(blocking=False):
        message = f"⚠️ Bulk import of '{display_filename}' refused - another bulk import is already running"
        update_log(instance, message)
        update_status(instance, "Bulk import refused: another bulk import is already running", color=StatusColor.WARNING.value)
        if schedule_id:
            send_notification(instance, message)
        return

    if schedule_id and filename:
        # Stamp the run only once it holds the lock: a refused run has not run,
        # and stamping it would hide the miss from catch-up.
        record_schedule_run(schedule_id)

    # Track successful poster uploads (those with ✅ or ♻️)
    tally = ProcessingCallbacks()
    errors = 0
    started_at = datetime.now(timezone.utc).isoformat()
    trigger = RunTrigger.SCHEDULED.value if schedule_id else RunTrigger.MANUAL.value
    notify_enabled = schedule_id or notify

    try:

        # Stop a run that has no Plex libraries, resolving them first if we're holding none
        if not globals.plex.ensure_libraries():
            update_status(instance, "Plex setup incomplete. Please check the settings.", color=StatusColor.DANGER.value)
            now = datetime.now(timezone.utc).isoformat()
            RunHistory().add_run(
                run_type=RunType.BULK.value,
                label=filename if filename else "bulk_import.txt",
                started_at=started_at,
                ended_at=now,
                trigger=trigger,
                outcome=RunOutcome.FAILED.value,
                job_id=schedule_id
            )
            if notify_enabled:
                send_notification(instance, f"🔴 Bulk import of '{display_filename}' failed to start • Plex setup incomplete", event=NotificationEvent.RUN_FAILED_TO_START.value)
            return

        globals.scrapes_running += 1
        globals.scrape_type = "bulk"
        notify_web(instance, "scrape_state", {"running": True, "type": globals.scrape_type})

        start_time = time.time()
        # Log the start of the bulk import process

        # Show the progress bar on the web UI
        message = f"{display_filename} • 0 of {len(parsed_urls)}"
        notify_web(instance, "progress_bar", {"percent" : 0, "message": message, "bar_type": "bulk"})
        globals.bulk_bar["active"] = True
        globals.bulk_bar["percent"] = 0
        globals.bulk_bar["message"] = message
        globals.bulk_bar["speed"] = "smooth"

        # Loop through the bulk list
        for i, parsed_line in enumerate(parsed_urls, 1):
            if globals.cancel_scrape:
                break

            try:
                scrape_and_upload(
                    instance=instance,
                    url=parsed_line.url,
                    options=parsed_line.options,
                    bulk={
                        "title": f"{display_filename} • {i-1} of {len(parsed_urls)}",
                        "index": i-1,
                        "total": len(parsed_urls)
                    },
                    tally=tally
                )
                #time.sleep(1)
            except ScraperException as e:
                update_log(instance, f"❌ Error processing line: '{parsed_line.url}'")
                debug_me(f"ScraperException: Failed to scrape URL: {parsed_line.url} | {str(e)}")
                errors += 1 
                pass

            percent = (i / len(parsed_urls)) * 100
            message = f"{display_filename} • {i} of {len(parsed_urls)}"
            notify_web(instance, "progress_bar", {"message": message, "percent" : percent, "bar_type": "bulk"})
            globals.bulk_bar["active"] = True
            globals.bulk_bar["percent"] = percent
            globals.bulk_bar["message"] = message
            globals.bulk_bar["speed"] = "smooth"

        # Log the completion of the bulk import process
        end_time = time.time()
        elapsed = elapsed_time(end_time - start_time)

        # A line that failed to scrape at all is an error the uploader never saw, so it is
        # handed to the tally rather than counted twice.
        total_errors = tally.errors(errors)
        outcome = tally.outcome(stopped=globals.cancel_scrape, extra_errors=errors)

        if globals.cancel_scrape:
            message = (
                "🛑 "
                + ("Scheduled b" if schedule_id else "B")
                + f"ulk import of '{display_filename}' stopped by user • "
                + f"{tally.assets_processed[0]} asset(s) processed • "
                + (f"{tally.cached_counter[0]} new in cache • " if tally.cached_counter[0] else "")
                + f"{tally.success_counter[0]} asset(s) updated"
                + (f" • {tally.locked_counter[0]} asset(s) locked (skipped)" if tally.locked_counter[0] else "")
                + (f" • {tally.failed_counter[0]} asset(s) failed" if tally.failed_counter[0] else "")
            )
            update_status(instance, message[2:], color=StatusColor.WARNING.value, sticky=False, spinner=False)
            notify_web(instance, "progress_bar", {"percent": 100, "bar_type": "bulk"})
            if notify_enabled:
                send_notification(instance, message, event=NotificationEvent.RUN_CANCELLED.value)
        else:
            message = (
                ("🏁 " if total_errors == 0 else "⚠️ ")
                + ("Scheduled b" if schedule_id else "B")
                + f"ulk import of '{display_filename}' completed "
                + (f"successfully in {elapsed} • " if total_errors == 0 else f"with {total_errors} error(s) in {elapsed}, check logs for details • ")
                + f"{tally.assets_processed[0]} asset(s) processed • "
                + (f"{tally.cached_counter[0]} new in cache • " if tally.cached_counter[0] else "")
                + f"{tally.success_counter[0]} asset(s) updated"
                + (f" • {tally.locked_counter[0]} asset(s) locked (skipped)" if tally.locked_counter[0] else "")
                + (f" • {tally.failed_counter[0]} asset(s) failed" if tally.failed_counter[0] else "")
            )
            update_status(instance, message[2:], color=StatusColor.SUCCESS.value if total_errors == 0 else StatusColor.WARNING.value, sticky=False, spinner=False)
            if notify_enabled:
                event = NotificationEvent.RUN_COMPLETED.value if total_errors == 0 else NotificationEvent.RUN_COMPLETED_WITH_ERRORS.value
                debug_me(f"Sending '{event}' notifications to {len(globals.config.apprise_urls)} configured notification channel(s).")
                send_notification(instance, message, event=event)
        RunHistory().add_run(
            run_type=RunType.BULK.value,
            label=filename if filename else "bulk_import.txt",
            started_at=started_at,
            ended_at=datetime.now(timezone.utc).isoformat(),
            trigger=trigger,
            outcome=outcome,
            assets_processed=tally.assets_processed[0],
            success_count=tally.success_counter[0],
            cached_count=tally.cached_counter[0],
            locked_count=tally.locked_counter[0],
            error_count=total_errors,
            job_id=schedule_id
        )
        update_log(instance, message)

    except Exception as bulk_import_exception:
        notify_web(instance, "progress_bar", { "percent": 100, "bar_type": "bulk" })
        update_status(instance, f"Error during bulk import: {bulk_import_exception}", color=StatusColor.DANGER.value)
        RunHistory().add_run(
            run_type=RunType.BULK.value,
            label=filename if filename else "bulk_import.txt",
            started_at=started_at,
            ended_at=datetime.now(timezone.utc).isoformat(),
            trigger=trigger,
            outcome=RunOutcome.FAILED.value,
            assets_processed=tally.assets_processed[0],
            success_count=tally.success_counter[0],
            cached_count=tally.cached_counter[0],
            locked_count=tally.locked_counter[0],
            error_count=tally.errors(errors),
            job_id=schedule_id
        )
        if notify_enabled:
            # scrape_and_upload only shields the loop from ScraperException - a PlexConnectorException
            # or anything else raised mid-run lands here after real work has already happened, so it must
            # not be reported as "failed to start". assets_processed only moves once an item has actually
            # been processed, so it tells the two cases apart.
            if tally.assets_processed[0] > 0:
                send_notification(instance, f"⚠️ Bulk import of '{display_filename}' stopped unexpectedly after {tally.assets_processed[0]} asset(s) processed • {bulk_import_exception}", event=NotificationEvent.RUN_COMPLETED_WITH_ERRORS.value)
            else:
                send_notification(instance, f"🔴 Bulk import of '{display_filename}' failed to start • {bulk_import_exception}", event=NotificationEvent.RUN_FAILED_TO_START.value)

    finally:
        globals.scrapes_running -= 1
        if globals.scrapes_running <= 0:
            globals.scrapes_running = 0
            globals.cancel_scrape = False
            notify_web(instance, "scrape_state", {"running": False, "type": globals.scrape_type})
            globals.scrape_type = "stopped"
        globals.bulk_import_lock.release()

# Scraped the URL then uploads what it's scraped to Plex or download to Kometa asset directory
def scrape_and_upload(
        instance: Instance,
        url: str,
        options: Options,
        bulk: dict = None,
        tally: ProcessingCallbacks = None
    ):
    """
    Scrape artwork from a URL and upload to Plex.

    This is now a thin wrapper around ArtworkProcessor that handles
    UI updates via callbacks.

    The caller owns the tally, so one run's counters survive across every URL in it.
    A caller that wants no counting can leave it out and get a throwaway one.
    """
    # Create callbacks for UI updates
    def status_callback(message: str, color: str, spinner: bool, sticky: bool):
        update_status(instance, message, color, sticky=sticky, spinner=spinner)

    def log_callback(message: str):
        update_log(instance, message)

    def debug_callback(message: str, context: str = None):
        debug_me(message, context)

    def progress_callback(current: int, total: int, title: str, bar_type:str = "main", bar_speed:str = "smooth"):
        percent = (current / total * 100) if total > 0 else 0
        notify_web(instance, "progress_bar", {"message": title, "percent": percent, "bar_type": bar_type, "bar_speed": bar_speed})
        if bar_type == "main":
            globals.main_bar["active"] = True
            globals.main_bar["percent"] = percent
            globals.main_bar["message"] = title
            globals.main_bar["speed"] = bar_speed
        elif bar_type == "bulk":
            globals.bulk_bar["active"] = True
            globals.bulk_bar["percent"] = percent
            globals.bulk_bar["message"] = title
            globals.bulk_bar["speed"] = bar_speed
            

    # replace() copies the tally's fields onto a new object, so the counter lists are
    # shared with the caller's tally and every URL in a run adds to the same numbers.
    callbacks = replace(
        tally if tally is not None else ProcessingCallbacks(),
        on_status_update=status_callback,
        on_log_update=log_callback,
        on_debug=debug_callback,
        on_progress_update=progress_callback
    )

    # Use the service to do the actual work
    try:
        processor = ArtworkProcessor(globals.plex, callbacks)
        title, author = processor.scrape_and_process(url, bulk, options)
        return title, author
    except PlexConnectorException as not_connected:
        debug_me(f"PlexConnectorException: {str(not_connected)}")
        update_status(instance, str(not_connected), StatusColor.DANGER.value)
        raise
    except ScraperException as scraper_error:
        debug_me(f"ScraperException: {str(scraper_error)}")
        raise
    except Exception as e:
        debug_me(f"Exception: {str(e)}")
        raise


def process_uploaded_artwork(
        instance: Instance,
        file_list,
        skipped,
        zip_title,
        zip_author,
        zip_source,
        options,
        filters,
        plex_title = None,
        plex_year = None
    ):
    """
    Process uploaded artwork files and upload to Plex or save to Kometa asset directory.

    This is now a thin wrapper around ArtworkProcessor that handles
    UI updates via callbacks.
    """
    # Create callbacks for UI updates
    def status_callback(message: str, color: str, spinner: bool, sticky: bool):
        update_status(instance, message, color, sticky=sticky, spinner=spinner)

    def log_callback(message: str):
        update_log(instance, message)

    def progress_callback(current: int, total: int, title: str, bar_type:str = "main", bar_speed:str = "smooth"):
        percent = (current / total * 100) if total > 0 else 0
        notify_web(instance, "progress_bar", {"message": title, "percent": percent, "bar_type": bar_type, "bar_speed": bar_speed})
        if bar_type == "main":
            globals.main_bar["active"] = True
            globals.main_bar["percent"] = percent
            globals.main_bar["message"] = title
            globals.main_bar["speed"] = bar_speed
        elif bar_type == "bulk":
            globals.bulk_bar["active"] = True
            globals.bulk_bar["percent"] = percent
            globals.bulk_bar["message"] = title
            globals.bulk_bar["speed"] = bar_speed

    def debug_callback(message: str, context: str = None):
        debug_me(message, context)

    callbacks = ProcessingCallbacks(
        on_status_update=status_callback,
        on_log_update=log_callback,
        on_progress_update=progress_callback,
        on_debug=debug_callback
    )

    # Use the service to do the actual work
    opts = Options(
        filters=filters,
        year=int(plex_year) if plex_year else None,
        temp=True if "temp" in options else False,
        stage=True if "stage" in options else False,
        force=True if "force" in options else False,
        skip_locked=True if "skip-locked" in options else False
    )
    processor = ArtworkProcessor(globals.plex, callbacks)

    # An uploaded ZIP is a run too, so it lands in the history alongside the scrapes and
    # the bulk imports. There is no cache crawl behind an upload, so cached stays at zero.
    started_at = datetime.now(timezone.utc).isoformat()
    label = plex_title or zip_title or "Uploaded artwork"
    outcome = RunOutcome.FAILED.value
    try:
        processor.process_uploaded_files(
            file_list=file_list,
            skipped=skipped,
            zip_title=zip_title,
            zip_author=zip_author,
            zip_source=zip_source,
            options=opts,
            override_title=plex_title
        )
        outcome = callbacks.outcome(stopped=globals.cancel_scrape)
    finally:
        RunHistory().add_run(
            run_type=RunType.UPLOAD.value,
            label=label,
            started_at=started_at,
            ended_at=datetime.now(timezone.utc).isoformat(),
            trigger=RunTrigger.MANUAL.value,
            outcome=outcome,
            assets_processed=callbacks.assets_processed[0],
            success_count=callbacks.success_counter[0],
            cached_count=0,
            locked_count=callbacks.locked_counter[0],
            error_count=callbacks.errors()
        )


# * Bulk import file I/O functions ---
def load_bulk_import_file(instance: Instance, filename = None):
    """Load the bulk import file into the text area."""
    try:
        # Get the current bulk_txt value from the config
        bulk_import_filename = filename if filename is not None else (config.bulk_txt if config and config.bulk_txt is not None else "bulk_import.txt")

        # Check if file exists
        if not globals.bulk_file_service.file_exists(bulk_import_filename):
            if instance.mode == "cli":
                print(f"File does not exist: {bulk_import_filename}")
            if instance.mode == "web":
                update_status(instance, f"File does not exist: {bulk_import_filename}", color=StatusColor.DANGER.value, sticky=False, spinner=False, icon="x-circle")
            return

        # Read file using service
        content = globals.bulk_file_service.read_file(bulk_import_filename)

        if instance.mode == "web":
            notify_web(instance, "load_bulk_import", {"loaded": True, "filename": bulk_import_filename, "bulk_import_text": content})

    except FileNotFoundError as e:
        debug_me(f"File not found: {str(e)}")
        notify_web(instance, "load_bulk_import", {"loaded": False, "error": f"File not found: {str(e)}"})
    except Exception as e:
        debug_me(f"Error loading bulk import file: {str(e)}")
        import traceback
        traceback.print_exc()
        notify_web(instance, "load_bulk_import", {"loaded": False, "error": str(e)})


def rename_bulk_import_file(instance: Instance, old_name, new_name) -> bool:
    debug_me(f"Renaming from {old_name} to {new_name}")

    if old_name != new_name:
        try:
            globals.bulk_file_service.rename_file(old_name, new_name)
            notify_web(instance, "rename_bulk_file", {"renamed": True, "old_filename": old_name, "new_filename": new_name})
            update_status(instance, f"Renamed to {new_name}", StatusColor.SUCCESS.value)
            update_log(instance, f"✏️ Renamed bulk import file from '{old_name}' to '{new_name}'")
            return True
        except Exception as e:
            notify_web(instance, "rename_bulk_file", {"renamed": False, "old_filename": old_name})
            update_status(instance, f"Could not rename {old_name}", StatusColor.WARNING.value)
            update_log(instance, f"🔴 Could not rename bulk import file '{old_name}'")
            debug_me(f"Could not rename bulk import file '{old_name}': {e}")
    return False


def delete_bulk_import_file(instance: Instance, file_name) -> bool:
    if file_name:
        try:
            globals.bulk_file_service.delete_file(file_name)
            notify_web(instance, "delete_bulk_file", {"deleted": True, "filename": file_name})
            update_status(instance, f"Deleted {file_name}", StatusColor.SUCCESS.value)
            update_log(instance, f"🗑️ Deleted bulk import file '{file_name}'")
            return True
        except Exception as e:
            notify_web(instance, "delete_bulk_file", {"deleted": False, "filename": file_name})
            update_status(instance, f"Could not delete {file_name}", StatusColor.WARNING.value)
            update_log(instance, f"🔴 Could not delete bulk import file '{file_name}'")
            debug_me(f"Could not delete bulk import file '{file_name}': {e}")
    return False


def save_bulk_import_file(instance: Instance, contents = None, filename = None, now_load = None):
    """Save the bulk import text area content to a file relative to the executable location."""
    if contents:
        try:
            bulk_import_filename = filename if filename is not None else (config.bulk_txt if config and config.bulk_txt is not None else "bulk_import.txt")

            debug_me(f"Saving {bulk_import_filename}")

            globals.bulk_file_service.write_file(contents, bulk_import_filename)

            update_status(instance, message=f"Bulk import file {bulk_import_filename} saved", color=StatusColor.SUCCESS.value)
            notify_web(instance, "save_bulk_import", {"saved": True, "now_load": now_load})
            update_log(instance, f"💾 Saved bulk import file '{bulk_import_filename}'")
        except Exception as e:
            update_status(instance, message="Error saving bulk import file", color=StatusColor.DANGER.value)
            notify_web(instance, "save_bulk_import", {"saved": False, "now_load": now_load})
            update_log(instance, f"🔴 Error saving bulk import file '{bulk_import_filename}'")
            debug_me(f"Error saving bulk import file '{bulk_import_filename}': {e}")


def check_for_bulk_import_file(instance: Instance):
    """Check if any .txt files exist in the bulk_imports folder before creating bulk_import.txt."""
    try:
        bulk_import_filename = config.bulk_txt if config and config.bulk_txt is not None else "bulk_import.txt"
        globals.bulk_file_service.ensure_default_file_exists(bulk_import_filename)
    except Exception as e:
        update_status(instance, message="Error creating bulk import file", color=StatusColor.DANGER.value)


def find_bulk_file(filename: str = None):
    """Find a bulk import file - returns full path if exists, None otherwise."""
    # Get the current bulk_txt value from the config
    bulk_import_filename = filename if filename is not None else (config.bulk_txt if config and config.bulk_txt is not None else "bulk_import.txt")

    # Use the service to check if file exists
    if globals.bulk_file_service.file_exists(bulk_import_filename):
        return globals.bulk_file_service.get_bulk_file_path(bulk_import_filename)
    return None


def setup_web_sockets():
    """
    Set up Flask routes and Socket.IO handlers.

    Delegates to web_routes module for better organization.
    """
    import web_routes

    # Set up HTTP routes
    web_routes.setup_routes(web_app, config)

    # Set up Socket.IO event handlers
    web_routes.setup_socket_handlers(config, filename_pattern)

    # Start the web server
    web_routes.start_web_server(web_app, DEFAULT_WEB_HOST, DEFAULT_WEB_PORT, globals.debug)

def check_image_orientation(image_path):
    """Check image orientation using ImageService."""
    return ImageService.check_orientation(image_path)

def sort_key(item):
    """Sort key for artwork items - uses UtilityService."""
    return UtilityService.sort_key(item)

# Autoupdate functions

def get_latest_version():
    """Fetch the latest release version from GitHub."""
    return globals.update_service.get_latest_version() if globals.update_service else None

def add_file_to_schedule_thread(instance: Instance, filename, schedule_id):
    if not instance:
        return

    # Overlap guard: don't let a catch-up run and a normally scheduled run for the
    # same file execute at the same time.
    if not globals.scheduler_service.try_start(filename):
        update_log(instance, f"⏳ Scheduled bulk import for '{filename}' skipped, a run is already in progress")
        debug_me(f"Skipped scheduled run for '{filename}': already in progress")
        return

    try:
        threading.Thread(target=process_bulk_file_on_schedule, args=(instance, filename, schedule_id,)).start()
    except Exception as e:
        # The guard must not leak, and an error here must not kill the scheduler thread
        if globals.scheduler_service:
            globals.scheduler_service.finish(filename)
        update_log(instance, f"🔴 Could not start scheduled bulk import for '{filename}' ({e})")

def record_schedule_run(schedule_id):
    """Record that a scheduled run for this bulk file has just started, so a future
    restart can tell whether a run was missed.

    A run executes the whole file, so every schedule the file carries gets the
    stamp. Stamping only the first would leave the file's other daily schedules
    with no last_run, which disables catch-up for them."""

    if globals.config is None:
        return
    try:
        for each_schedule in globals.config.schedules:
            if each_schedule.get("id") == schedule_id:
                each_schedule["last_run"] = datetime.now().isoformat()
                job = globals.scheduler_service.scheduled_jobs.get(schedule_id)
                if job and hasattr(job, "next_run") and job.next_run:
                    each_schedule["next_run"] = job.next_run.isoformat()
                else:
                    sched = BulkSchedule(**each_schedule)
                    each_schedule["nex_trun"] = sched.compute_next_run()

        globals.config.save()
    except Exception as e:
        # A failed stamp costs one catch-up decision; letting it propagate would
        # kill the scheduler thread, which costs every future run.
        debug_me(f"Could not record schedule run for job ID '{schedule_id}': {e}")

def process_bulk_file_on_schedule(instance: Instance, filename, schedule_id):

    instance.broadcast = True

    try:
        bulk_import_file = find_bulk_file(filename)
        if bulk_import_file:
            with open(bulk_import_file, "r", encoding="utf-8") as file:
                content = file.read()
            if content:
                update_log(instance, f"🕘 Scheduled bulk import started for '{filename}'")
                debug_me(f"Scheduled import started for instance {instance.id} mode {instance.mode}")
                send_notification(instance, f"🕘 Scheduled bulk import started for '{filename}'", event=NotificationEvent.RUN_STARTED.value)
                run_bulk_import_scrape_in_thread(instance, content, filename, schedule_id=schedule_id)
            else:
                update_log(instance, f"⏭️ Scheduled bulk import of '{filename}' skipped • file is empty")
                now = datetime.now(timezone.utc).isoformat()
                RunHistory().add_run(
                    run_type=RunType.BULK.value,
                    label=filename,
                    started_at=now,
                    ended_at=now,
                    trigger=RunTrigger.SCHEDULED.value,
                    outcome=RunOutcome.SKIPPED.value,
                    job_id=schedule_id
                )
                send_notification(instance, f"⏭️ Scheduled bulk import of '{filename}' skipped • file is empty", event=NotificationEvent.RUN_SKIPPED.value)
        else:
            update_log(instance, f"🔴 Bulk file does not exist: {filename}")
            now = datetime.now(timezone.utc).isoformat()
            RunHistory().add_run(
                run_type=RunType.BULK.value,
                label=filename,
                started_at=now,
                ended_at=now,
                trigger=RunTrigger.SCHEDULED.value,
                outcome=RunOutcome.FAILED.value,
                job_id=schedule_id
            )
            send_notification(instance, f"🔴 Scheduled bulk import of '{filename}' failed to start • file does not exist", event=NotificationEvent.RUN_FAILED_TO_START.value)
            return
    except FileNotFoundError:
        update_log(instance, f"🔴 Scheduled bulk import failed due to missing file ({filename})")
        now = datetime.now(timezone.utc).isoformat()
        RunHistory().add_run(
            run_type=RunType.BULK.value,
            label=filename,
            started_at=now,
            ended_at=now,
            trigger=RunTrigger.SCHEDULED.value,
            outcome=RunOutcome.FAILED.value,
            job_id=schedule_id
        )
        send_notification(instance, f"🔴 Scheduled bulk import of '{filename}' failed to start • file not found", event=NotificationEvent.RUN_FAILED_TO_START.value)
    except Exception as e:
        update_log(instance, f"🔴 Scheduled bulk import unexpectedly failed ({str(e)})")
        send_notification(instance, f"🔴 Scheduled bulk import of '{filename}' failed to start • {e}", event=NotificationEvent.RUN_FAILED_TO_START.value)
        now = datetime.now(timezone.utc).isoformat()
        RunHistory().add_run(
            run_type=RunType.BULK.value,
            label=filename,
            started_at=now,
            ended_at=now,
            trigger=RunTrigger.SCHEDULED.value,
            outcome=RunOutcome.FAILED.value,
            job_id=schedule_id
        )
    finally:
        if globals.scheduler_service:
            globals.scheduler_service.finish(filename)


#Initialises the scheduler when the script is run
def setup_scheduler_on_first_load(instance: Instance):
    """
    Initialises the scheduler when the script is run and sets up each schedule from the config file.

    Args:
        instance: Instance ID

    Returns: None
    """
    if globals.config is None:
        return

    # If there are no scheduled jobs already...
    if not globals.scheduler_service.has_schedules():
        for each_schedule in globals.config.schedules:
            new_schedule = BulkSchedule(**each_schedule)
            if new_schedule.last_run_status == "never_run":
                new_schedule.compute_next_run()

            # Create the callback for this schedule
            def schedule_callback(filename=new_schedule.file, schedule_id=new_schedule.id):
                add_file_to_schedule_thread(instance, filename, schedule_id)

            # Add to scheduler service, reusing the id already stored in
            # config so the schedule keeps the same identity across reloads.
            # A malformed persisted entry is skipped, not fatal: one bad line in
            # config.json must not stop the app starting.
            try:
                globals.scheduler_service.add_schedule(
                    sched=new_schedule,
                    callback=schedule_callback
                )
                last_run_message = "Never" if new_schedule.last_run_status == "never_run" else f"{new_schedule.last_run} ({new_schedule.last_run_status})"
                if new_schedule.time:
                    debug_me(f"Added schedule ID '{new_schedule.id}' for '{new_schedule.file}': Every day at {new_schedule.time} | Last run: {last_run_message} | Next run: {new_schedule.next_run}")
                elif new_schedule.interval_value:
                    debug_me(f"Added schedule ID '{new_schedule.id}' for '{new_schedule.file}': Every {new_schedule.interval_value} {new_schedule.interval_unit} | Last run: {last_run_message} | Next run: {new_schedule.next_run}")
            except ValueError as e:
                update_log(instance, f"🔴 Skipping invalid schedule for '{new_schedule.file}': {e}")
                debug_me(f"Skipping invalid schedule entry {each_schedule}: {e}")


        # Start the scheduler
        if globals.scheduler_service.start():
            debug_me("Scheduler started.")

def catch_up_missed_schedules(instance: Instance):
    """Run any schedule (daily or interval) that was due while the app was not running.

    Called from main only after the Plex libraries are connected: a catch-up run
    fired before that point executes against empty libraries, fails every item,
    and burns its one chance to be caught up."""
    if globals.config is None:
        return
    for each_schedule in globals.config.schedules:
        catch_up_missed_schedule(
            instance=instance,
            sched=BulkSchedule(**each_schedule)
        )


def catch_up_missed_schedule(instance: Instance, sched: BulkSchedule):
    """
    Run a scheduled bulk import that was due while the app was not running, if it falls
    inside the configured catch-up window. Otherwise, just log that it was skipped.

    Args:
        instance: Instance to run/log the catch-up as
        filename: Bulk file the schedule is for
        schedule_time: Time of day the schedule runs, as "HH:MM"
        last_run: ISO timestamp of the last time this schedule ran, or None
    """
    window_minutes = globals.config.catch_up_window_minutes if globals.config else 0

    due, within_window = globals.scheduler_service.get_missed_run(sched=sched, window=window_minutes)

    if due is None:
        return

    due_display = due.strftime("%Y-%m-%d %H:%M")

    if within_window:
        update_log(instance, f"⏰ Catching up missed scheduled run for '{sched.file}' (was due {due_display})")
        debug_me(f"Catch-up run for '{sched.file}', due {due.isoformat()}, window {window_minutes} minutes")
        add_file_to_schedule_thread(instance, sched.file, sched.id)
    else:
        update_log(instance, f"⚠️ Scheduled run for '{sched.file}' was missed and is outside the catch-up window (was due {due_display})")
        debug_me(f"Missed scheduled run for '{sched.file}', due {due.isoformat()}, outside catch-up window of {window_minutes} minutes")


# Kept as a hook for the "load_config" socket event. There is nothing to
# resync here: a schedule's id is the single source of truth shared between
# config.json and the running scheduler, and every add/edit/delete/rename
# already keeps the two in step as they happen, so reloading config.json
# from disk does not need to tear down and rebuild the live jobs.
def update_scheduled_jobs():
    pass


# * Main Initialization ---
if __name__ == "__main__":

    # Create an instance object including a unique id and "cli" mode to pass around
    cli_instance = Instance(uuid.uuid4(), InstanceMode.CLI.value)

    scheduler_thread = None

    # Updated regex: "Movie Title (YYYY).png" OR "Movie Title.png"
    filename_pattern = re.compile(VALID_FILENAME_PATTERN, re.IGNORECASE)

    # Process command line arguments
    args = arguments.parse_arguments()

    # Turn on debug mode if required
    globals.debug = args.debug

    # Store what the user wants to do.  If it's blank we'll load the GUI.
    cli_command = args.command

    # Store the options passed as arguments
    cli_options = Options(
        add_posters=args.add_posters,
        add_sets=args.add_sets,
        force=args.force,
        skip_locked=args.skip_locked,
        allow_artist_updates=args.allow_artist_updates,
        filters=args.filters,
        exclude=args.exclude,
        year=args.year,
        kometa=args.kometa,
        stage=args.stage,
        temp=args.temp,
        no_cache=args.no_cache
    )  # Arguments per url to process

    # Create config as a global object
    config = Config()
    globals.config = config  # Also store in globals for cross-module access

    # Load the config from the config.json file
    try:
        config.load()
    except ConfigLoadError:
        sys.exit("Can't load config.json file.  Please check that the file exists and is in the correct format.")
    except Exception as config_load_exception:
        sys.exit(f"Unexpected error when loading config.json file: {str(config_load_exception)}")

    # Create services
    globals.bulk_file_service = BulkFileService(get_exe_dir())
    globals.scheduler_service = SchedulerService(check_interval=SCHEDULER_CHECK_INTERVAL)
    globals.webhook_service = WebhookService()
    globals.update_service = UpdateService(
        github_repo=GITHUB_REPO,
        current_version=current_version,
        check_interval=UPDATE_CHECK_INTERVAL
    )


    # Make sure there's at least one bulk_import file
    check_for_bulk_import_file(cli_instance)

    # Create a connector for Plex
    globals.plex = PlexConnector(config.base_url, config.token)
    # Initialize the library index object (it will not create the index if there are no libraries defined yet)
    # The actual index will be created the first time it's needed, and will not be recreated unless it expires
    # or the defined libraries have changed. This is controlled by the _initialize_index method in PlexLibraryIndex
    globals.plex._initialize_index()

    # Check for CLI arguments regardless of interactive_cli flag
    if cli_command:

        # Connect to the TV and Movie libraries
        try:
            globals.plex.set_tv_libraries(config.tv_library)
        except PlexConnectorException as e:
            print("=" * 70)
            print("ERROR: Could not connect to Plex server")
            print("=" * 70)
            print(f"{e}\n")
            print("Please check your config.json settings:")
            print(f"  - base_url: {config.base_url}")
            print(f"  - token: {config.token[:10]}..." if config.token else "  - token: (not set)")
            print("\nEnsure your Plex server is running and accessible.")
            print("=" * 70)
            sys.exit(1)

        try:
            globals.plex.set_movie_libraries(config.movie_library)
        except PlexConnectorException as e:
            print("=" * 70)
            print("ERROR: Could not connect to Plex movie libraries")
            print("=" * 70)
            print(f"{e}")
            print("=" * 70)
            sys.exit(1)

        # Handle the CLI options if we're not using the web ui
        if cli_command == 'bulk':

            # Remove some of the command line options which should be specified per line
            cli_options.add_posters = False
            cli_options.add_sets = False
            cli_options.year = None
            cli_options.clear_filters()

            # Process using the bulk filename if supplied, else the bulk file set in the config
            parse_bulk_file_from_cli(cli_instance, args.bulk_file if args.bulk_file else os.path.join("bulk_imports", config.bulk_txt))

        # Now we're looking at URLs - firstly one containing a TPDb user
        elif "/user/" in cli_command:

            # Remove some of the command line options which aren't applicable to user scraping
            cli_options.year = None
            cli_options.add_posters = False
            cli_options.add_sets = False
            try:
                tally = ProcessingCallbacks()
                scrape_and_upload(
                    instance=cli_instance,
                    url=cli_command,
                    options=cli_options,
                    tally=tally
                )
                debug_me(f"Finished scraping TPDb user URL from CLI with {tally.success_counter[0]} asset(s) updated", "__main__")
            except Exception as e:
                debug_me(f"Error scraping TPDb user URL from CLI: {str(e)}", "__main__")
                update_status(cli_instance, str(e), color=StatusColor.DANGER.value)

        # User passed in a poster or set URL, so let's process that
        else:
            try:
                tally = ProcessingCallbacks()
                scrape_and_upload(
                    instance=cli_instance,
                    url=cli_command,
                    options=cli_options,
                    tally=tally
                )
                debug_me(f"Finished scraping URL from CLI with {tally.success_counter[0]} asset(s) updated", "__main__")
            except Exception as e:
                debug_me(f"Error scraping URL from CLI: {str(e)}", "__main__")
                update_status(cli_instance, str(e),color=StatusColor.DANGER.value)
    else:

        # If no CLI arguments, proceed with UI creation (if not in interactive CLI mode)
        if not interactive_cli:
            update_log(cli_instance, f"🚀 Starting Artwork Uploader {CURRENT_VERSION} in web mode")
            if globals.docker:
                update_log(cli_instance, "🐳 Running in Docker environment")
            # Setup scheduler only in the main process to avoid duplication
            if os.getenv("WERKZEUG_RUN_MAIN") == "true" or not globals.debug:
                update_log(cli_instance, "🗓️ Setting up scheduler for scheduled tasks")
                debug_me("This is the main process - setting up scheduler")
                setup_scheduler_on_first_load(cli_instance)
            else:
                debug_me("Not the main process - skipping scheduler setup")
                update_log(cli_instance, "⚠️ Skipping scheduler setup in debug mode")            

            # Connect to the TV and Movie libraries
            plex_connected = True
            try:
                globals.plex.set_tv_libraries(config.tv_library)
            except PlexConnectorException as e:
                print("=" * 70)
                print("WARNING: Could not connect to Plex TV libraries")
                print("=" * 70)
                print(f"{e}\n")
                print("The web UI will still start, but you won't be able to upload artwork")
                print("until you fix the Plex connection in Settings.\n")
                plex_connected = False

            try:
                globals.plex.set_movie_libraries(config.movie_library)
            except PlexConnectorException as e:
                if plex_connected:  # Only print if we didn't already print for TV
                    print("=" * 70)
                    print("WARNING: Could not connect to Plex Movie libraries")
                    print("=" * 70)
                    print(f"{e}\n")
                    print("The web UI will still start, but you won't be able to upload artwork")
                    print("until you fix the Plex connection in Settings.\n")

            # Catch up missed schedules only now that the libraries are connected
            if plex_connected and (os.getenv("WERKZEUG_RUN_MAIN") == "true" or not globals.debug):
                catch_up_missed_schedules(cli_instance)

            # Create the app and web server

            web_app = Flask(__name__, template_folder="templates")

            # Configure session for authentication
            import secrets
            from datetime import timedelta
            web_app.config['SECRET_KEY'] = secrets.token_hex(32)
            web_app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

            globals.web_socket = SocketIO(web_app, cors_allowed_origins="*", async_mode="threading")

            # Start update checker using UpdateService
            def on_update_available(version: str):
                instance = Instance(broadcast=True)
                update_log(instance, f"🚨 Update available: {version} (current: {current_version})")
                notify_web(instance, "version_check", { "current_version": current_version, "new_version": version, "docker": "true" if globals.docker else "false" })

            globals.update_service.start_periodic_check(on_update_available)

            setup_web_sockets()

