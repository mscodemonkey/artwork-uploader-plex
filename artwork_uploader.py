import uuid
import os
import re
from core import globals
import threading
import sys
import time

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
from core.enums import InstanceMode, StatusColor
from services import (
    BulkFileService,
    ImageService,
    SchedulerService,
    WebhookService,
    UtilityService
)
from services.artwork_processor import ArtworkProcessor
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
scheduled_jobs = {}  # Legacy - kept for backwards compatibility
scheduled_jobs_by_file = {}  # Legacy - kept for backwards compatibility
# Services moved to core.globals for proper cross-module access
config = None  # Initialized in main



# ---------------------- CORE FUNCTIONS ----------------------

def parse_bulk_file_from_cli(instance: Instance, file_path):

    """
    Load and parse the URLs from a bulk import file, then scrape them with any options set for that URL.
    """

    # Open the file and read the contents
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            urls = file.readlines()
    except FileNotFoundError:
        print("File not found. Please enter a valid file path.")

    start_time = time.time()
    update_log(instance, f"🎬 Bulk process started for '{os.path.basename(file_path)}'")

    # Loop through the file, process the URL and options, then scrape according to the URL
    for n, line in enumerate(urls, 1):

        # Skip comments
        if is_not_comment(line):

            # Parse the line to extract the URL and options
            try:
                parsed_url = parse_url_and_options(line)
            except InvalidUrl as e:
                update_log(instance, f"❌ Invalid URL found in bulk import file '{os.path.basename(file_path)}', line {n}: '{str(e)}'")
                continue
            except InvalidFlag as e:
                update_log(instance, f"❌ One or more invalid flags found in bulk import file '{os.path.basename(file_path)}', line {n}: {str(e)}")
                continue

            try:
                success_counter = [0]
                scrape_and_upload(instance, parsed_url.url, parsed_url.options, False, success_counter)
            except ScraperException as e:
                debug_me(f"ScraperException: Error processing {parsed_url.url}: {str(e)}")
            except Exception as e:
                debug_me(f"Unknown Exception: Error processing {parsed_url.url}: {str(e)}")

    end_time = time.time()
    elapsed = elapsed_time(end_time - start_time)
    update_log(instance, f"🏁 Bulk process completed in {elapsed} for '{os.path.basename(file_path)}'")

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

    try:
        if instance.mode == "web":
            notify_web(instance, "element_disable", { "element": ["scrape_url", "scrape_button", "bulk_button"], "mode": True })
        globals.scrapes_running += 1
        notify_web(instance, "scrape_state", { "running": True, "type": "scrape" })
        # Check if the Plex TV and movie libraries are configured
        if globals.plex.tv_libraries is None or globals.plex.movie_libraries is None:
            update_status(instance, "Plex setup incomplete. Please configure your settings.", color=StatusColor.WARNING.value)
            globals.scrapes_running -= 1
            return

        # Process the URL and options passed from the GUI or website
        parsed_line = parse_url_and_options(url)

        success_counter = [0]
        title, author = scrape_and_upload(instance, parsed_line.url, parsed_line.options, False, success_counter)

        # Update the web ui bulk list with this URL and artwork (only if it's not already in the bulk list)
        if instance.mode == "web" and parsed_line.options.add_to_bulk and title:
            notify_web(instance, "add_to_bulk_list", {"url": url, "title": title, "author": author})

    except ScraperException as scraping_error:
        update_status(instance, f"{scraping_error}", color=StatusColor.DANGER.value)

    finally:
        globals.scrapes_running -= 1
        if globals.scrapes_running <= 0:
            globals.scrapes_running = 0
            globals.cancel_scrape = False
            notify_web(instance, "scrape_state", { "running": False, "type": "scrape" })
        if instance.mode == "web":
            notify_web(instance, "element_disable", { "element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False })


def run_bulk_import_scrape_in_thread(instance: Instance, web_list = None, filename = None, scheduled: bool = False) -> None:

    """Run the bulk import scrape in a separate thread."""

    if instance.mode == "web":
        notify_web(instance, "element_disable", { "element": ["scrape_url", "scrape_button", "bulk_button"], "mode": True })

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
        notify_web(instance, "element_disable", { "element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False })
        return

    # Pass the processing of the parsed URLs off to a thread
    try:
        process_bulk_import_from_ui(instance, parsed_urls, filename, scheduled)
    except Exception:
        raise


def process_bulk_import_from_ui(instance: Instance, parsed_urls: list, filename: str = None, scheduled: bool = False) -> None:

    """
    Process the bulk import scrape, based on the contents of the Bulk Import tab in the GUI.

    The bulk import list doesn't need to have been saved, it will use the list as it exists in the GUI currently.

    Args:
        instance:
        parsed_urls:    The URLs to scrape.  These can be theposterdb poster, set or user URL or a mediux set URL.
        filename:       The filename of the bulk import file being processed.
    """

    # Track successful poster uploads (those with ✅ or ♻️)
    success_counter = [0]
    assets_processed = [0]
    cached_counter = [0]
    errors = 0

    try:
        globals.scrapes_running += 1
        notify_web(instance, "scrape_state", {"running": True, "type": "bulk"})

        # Check if plex setup returned valid values
        if globals.plex.tv_libraries is None or globals.plex.movie_libraries is None:
            update_status(instance, "Plex setup incomplete. Please check the settings.", color=StatusColor.DANGER.value)
            globals.scrapes_running -= 1
            return

        start_time = time.time()
        # Log the start of the bulk import process
        display_filename = filename if filename else "bulk_import.txt"

        # Show the progress bar on the web UI
        notify_web(instance, "progress_bar", {"percent" : 0, "message": f"{display_filename} • 0 of {len(parsed_urls)}", "bar_type": "bulk"})

        # Loop through the bulk list
        for i, parsed_line in enumerate(parsed_urls, 1):
            if globals.cancel_scrape:
                break

            try:
                scrape_and_upload(instance, parsed_line.url, parsed_line.options, True, success_counter, assets_processed, cached_counter=cached_counter)
                #time.sleep(1)
            except ScraperException as e:
                update_log(instance, f"❌ Error processing line: '{parsed_line.url}'")
                debug_me(f"ScraperException: Failed to scrape URL: {parsed_line.url} | {str(e)}")
                errors += 1 
                pass

            percent = (i / len(parsed_urls)) * 100
            notify_web(instance, "progress_bar", {"message": f"{display_filename} • {i} of {len(parsed_urls)}", "percent" : percent, "bar_type": "bulk"})

        # Log the completion of the bulk import process
        end_time = time.time()
        elapsed = elapsed_time(end_time - start_time)

        if globals.cancel_scrape:
            message = (
                "🛑 "
                + ("Scheduled b" if scheduled else "B")
                + f"ulk import of '{display_filename}' stopped by user • "
                + f"{assets_processed[0]} asset(s) processed • "
                + (f"{cached_counter[0]} new in cache • " if cached_counter[0] else "")
                + f"{success_counter[0]} asset(s) updated"
            )
            update_status(instance, message[2:], color=StatusColor.WARNING.value, sticky=False, spinner=False)
            notify_web(instance, "progress_bar", {"percent": 100, "bar_type": "bulk"})
        else:
            message = (
                ("🏁 " if errors == 0 else "⚠️ ")
                + ("Scheduled b" if scheduled else "B")
                + f"ulk import of '{display_filename}' completed "
                + (f"successfully in {elapsed} • " if errors == 0 else f"with {errors} error(s) in {elapsed}, check logs for details • ")
                + f"{assets_processed[0]} asset(s) processed • "
                + (f"{cached_counter[0]} new in cache • " if cached_counter[0] else "")
                + f"{success_counter[0]} asset(s) updated"
            )
            update_status(instance, message[2:], color=StatusColor.SUCCESS.value if errors == 0 else StatusColor.WARNING.value, sticky=False, spinner=False)
        update_log(instance, message)
        if scheduled:
            debug_me(f"Sending notifications to {len(globals.config.apprise_urls)} notification service(s).")
            send_notification(instance, message)

    except Exception as bulk_import_exception:
        notify_web(instance, "progress_bar", { "percent": 100, "bar_type": "bulk" })
        update_status(instance, f"Error during bulk import: {bulk_import_exception}", color=StatusColor.DANGER.value)

    finally:
        globals.scrapes_running -= 1
        if globals.scrapes_running <= 0:
            globals.scrapes_running = 0
            globals.cancel_scrape = False
            notify_web(instance, "scrape_state", {"running": False, "type": "bulk"})
        notify_web(instance, "element_disable", { "element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False })

# Scraped the URL then uploads what it's scraped to Plex or download to Kometa asset directory
def scrape_and_upload(instance: Instance, url, options, bulk=False, success_counter=None, assets_processed=None, cached_counter=None):
    """
    Scrape artwork from a URL and upload to Plex.

    This is now a thin wrapper around ArtworkProcessor that handles
    UI updates via callbacks.
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

    callbacks = ProcessingCallbacks(
        on_status_update=status_callback,
        on_log_update=log_callback,
        on_debug=debug_callback,
        on_progress_update=progress_callback,
        success_counter=success_counter,
        assets_processed=assets_processed,
        cached_counter=cached_counter
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


def process_uploaded_artwork(instance: Instance, file_list, skipped, zip_title, zip_author, zip_source, options, filters, plex_title = None, plex_year = None):
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
    processor.process_uploaded_files(file_list, skipped, zip_title, zip_author, zip_source, opts, override_title=plex_title)


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


def rename_bulk_import_file(instance: Instance, old_name, new_name):
    debug_me(f"Renaming from {old_name} to {new_name}")

    if old_name != new_name:
        try:
            globals.bulk_file_service.rename_file(old_name, new_name)
            notify_web(instance, "rename_bulk_file", {"renamed": True, "old_filename": old_name, "new_filename": new_name})
            update_status(instance, f"Renamed to {new_name}", StatusColor.SUCCESS.value)
            update_log(instance, f"✏️ Renamed bulk import file from '{old_name}' to '{new_name}'")
        except Exception as e:
            notify_web(instance, "rename_bulk_file", {"renamed": False, "old_filename": old_name})
            update_status(instance, f"Could not rename {old_name}", StatusColor.WARNING.value)
            update_log(instance, f"🔴 Could not rename bulk import file '{old_name}'")
            debug_me(f"Could not rename bulk import file '{old_name}': {e}")


def delete_bulk_import_file(instance: Instance, file_name):
    if file_name:
        try:
            globals.bulk_file_service.delete_file(file_name)
            notify_web(instance, "delete_bulk_file", {"deleted": True, "filename": file_name})
            update_status(instance, f"Deleted {file_name}", StatusColor.SUCCESS.value)
            update_log(instance, f"🗑️ Deleted bulk import file '{file_name}'")
        except Exception as e:
            notify_web(instance, "delete_bulk_file", {"deleted": False, "filename": file_name})
            update_status(instance, f"Could not delete {file_name}", StatusColor.WARNING.value)
            update_log(instance, f"🔴 Could not delete bulk import file '{file_name}'")
            debug_me(f"Could not delete bulk import file '{file_name}': {e}")


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

def check_for_updates_periodically():
    """Background task to check for updates periodically - now handled by UpdateService."""
    # This function is kept for backwards compatibility but is no longer used
    # The UpdateService handles periodic checks automatically
    pass




def add_file_to_schedule_thread(instance: Instance, filename):
    if instance:
        threading.Thread(target=process_bulk_file_on_schedule, args=(instance, filename,)).start()


def process_bulk_file_on_schedule(instance: Instance, filename):

    instance.broadcast = True

    try:
        bulk_import_file = find_bulk_file(filename)
        if bulk_import_file:
            with open(bulk_import_file, "r", encoding="utf-8") as file:
                content = file.read()
            if content:
                update_log(instance, f"🕘 Scheduled bulk import started for '{filename}'")
                debug_me(f"Scheduled import started for instance {instance.id} mode {instance.mode}")
                send_notification(instance, f"🕘 Scheduled bulk import started for '{filename}'")
                run_bulk_import_scrape_in_thread(instance, content, filename, scheduled=True)
        else:
            update_log(instance, f"🔴 Bulk file does not exist: {filename}")
            return
    except FileNotFoundError:
        update_log(instance, f"🔴 Scheduled bulk import failed due to missing file ({filename})")
    except Exception as e:
        update_log(instance, f"🔴 Scheduled bulk import unexpectedly failed ({str(e)})")


# Legacy functions - now handled by SchedulerService
# Kept for backwards compatibility but no longer used internally


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
            schedule_file = each_schedule.get("file")
            schedule_time = each_schedule.get("time")

            # Create the callback for this schedule
            def schedule_callback(filename=schedule_file):
                add_file_to_schedule_thread(instance, filename)

            # Add to scheduler service
            job_id = globals.scheduler_service.add_schedule(
                schedule_file,
                schedule_time,
                schedule_callback
            )

            # Store job reference in config and legacy dicts
            each_schedule["jobReference"] = job_id
            scheduled_jobs_by_file[schedule_file] = job_id

        # Start the scheduler
        if globals.scheduler_service.start():
            debug_me("Scheduler started.")

        debug_me(globals.config.schedules)


# Update the job references for any scheduled jobs if we reload the config file
def update_scheduled_jobs():
    if globals.config is None:
        return
    for each_schedule in globals.config.schedules:
        schedule_file = each_schedule.get("file", "")
        if schedule_file and schedule_file in scheduled_jobs_by_file:
            each_schedule["jobReference"] = scheduled_jobs_by_file[schedule_file]


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
    cli_options = Options(add_posters=args.add_posters,
                          add_sets=args.add_sets,
                          force=args.force,
                          skip_locked=args.skip_locked,
                          filters=args.filters,
                          exclude=args.exclude,
                          year=args.year,
                          kometa=args.kometa,
                          stage=args.stage,
                          temp=args.temp,
                          no_cache=args.no_cache)  # Arguments per url to process

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
                success_counter = [0]
                scrape_and_upload(cli_instance, cli_command, cli_options, False, success_counter)
                debug_me(f"Finished scraping TPDb user URL from CLI with {success_counter[0]} asset(s) updated", "__main__")
            except Exception as e:
                debug_me(f"Error scraping TPDb user URL from CLI: {str(e)}", "__main__")
                update_status(cli_instance, str(e), color=StatusColor.DANGER.value)

        # User passed in a poster or set URL, so let's process that
        else:
            try:
                success_counter = [0]
                scrape_and_upload(cli_instance, cli_command, cli_options, False, success_counter)
                debug_me(f"Finished scraping URL from CLI with {success_counter[0]} asset(s) updated", "__main__")
            except Exception as e:
                debug_me(f"Error scraping URL from CLI: {str(e)}", "__main__")
                update_status(cli_instance, str(e),color=StatusColor.DANGER.value)
    else:

        # If no CLI arguments, proceed with UI creation (if not in interactive CLI mode)
        if not interactive_cli:
            update_log(cli_instance, f"🚀 Starting Artwork Uploader {CURRENT_VERSION} in web mode")
            if globals.docker:
                update_log(cli_instance, "🐳 Running in Docker environment", force_print=True)
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

