import os
import re
import sys
import threading
import traceback
import uuid

import eventlet
eventlet.monkey_patch()
from flask_cors import CORS

from core import globals
from core.config import Config
from core.constants import (
    CURRENT_VERSION,
    GITHUB_REPO,
    DEFAULT_BULK_IMPORT_FILE,
    DEFAULT_CONFIG_PATH,
    DEFAULT_LOGS_DIR,
    DEFAULT_WEB_PORT,
    SCHEDULER_CHECK_INTERVAL,
    UPDATE_CHECK_INTERVAL,
    MIN_PYTHON_MAJOR,
    MIN_PYTHON_MINOR,
    TPBD_USER_BASE_PATH
)
from core.enums import InstanceMode
from core.exceptions import ConfigLoadError, PlexConnectorException, ScraperException, InvalidUrl, InvalidFlag
from logging_config import setup_logging, get_logger
from models import arguments
from models.instance import Instance
from models.options import Options
from plex.plex_connector import PlexConnector
from scrapers.theposterdb_scraper import ThePosterDBScraper
from services import (
    BulkFileService,
    ImageService,
    ArtworkProcessor,
    ProcessingCallbacks,
    SchedulerService,
    UtilityService
)
from utils.notifications import update_log, update_status, notify_web, debug_me, send_notification


module_logger = get_logger(__name__)

# ----------------------------------------------
# Important for autoupdater
current_version = CURRENT_VERSION
# ----------------------------------------------

if sys.version_info[0] != MIN_PYTHON_MAJOR or sys.version_info[1] < MIN_PYTHON_MINOR:
    sys.stderr.write(
        f"Version: {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]} is not compatible with Artwork Uploader, please upgrade to Python {MIN_PYTHON_MAJOR}.{MIN_PYTHON_MINOR}+\n")
    sys.exit(0)

try:
    from PIL import Image
    from flask import Flask, render_template
    from flask_socketio import SocketIO
except ImportError as e:
    sys.stderr.write(f"""{'=' * 70}
    ERROR: Required dependencies are missing or incompatible
    {'=' * 70}

    Details: {e}

    This usually means one of the following:
      1. Requirements not installed: Run 'pip install -r requirements.txt'
      2. Wrong Python version: Requires Python 3.10+
      3. Architecture mismatch (Apple Silicon): Reinstall dependencies

    For architecture issues on Apple Silicon Macs:
      pip uninstall Pillow Flask flask-socketio -y
      pip install Pillow Flask flask-socketio

    Or use a virtual environment:
      python3 -m venv .venv
      source .venv/bin/activate
      pip install -r requirements.txt

    See README.md for more troubleshooting help.
    {'=' * 70}
""")
    sys.exit(1)

globals.docker = os.getenv("RUNNING_IN_DOCKER") == "1"

# ! Interactive CLI mode flag
# Set to False when building the executable with PyInstaller for it launches the web UI by default
interactive_cli = False
mode = InstanceMode.CLI.value
scheduled_jobs = {}  # Legacy - kept for backwards compatibility
scheduled_jobs_by_file = {}  # Legacy - kept for backwards compatibility
# Services moved to core.globals for proper cross-module access
config = None  # Initialized in main

github_repo = GITHUB_REPO  # For autoupdater


# ---------------------- CORE FUNCTIONS ----------------------

def parse_bulk_file_from_cli(instance: Instance, file_path):
    """
    Load and parse the URLs from a bulk file, then scrape them with any options set for that URL.
    """

    # Open the file and read the contents
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            urls = file.readlines()
    except FileNotFoundError:
        module_logger.error(
            "File not found. Please enter a valid file path.", exc_info=True)

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

            # Parse according to whether it's a user portfolio or poster / set URL
            if TPBD_USER_BASE_PATH in parsed_url.url:
                try:
                    scrape_tpdb_user(instance, parsed_url.url,
                                     parsed_url.options)
                except ScraperException as scraper_error:
                    module_logger.error(str(scraper_error), exc_info=True)
                except Exception as unknown_error:
                    module_logger.error(str(unknown_error), exc_info=True)
            else:
                try:
                    success_counter = [0]
                    scrape_and_upload(
                        instance, parsed_url.url, parsed_url.options, success_counter)
                except ScraperException as e:
                    module_logger.error(
                        f"ScraperException: Error processing {parsed_url.url}: {str(e)}", exc_info=True)
                except Exception as e:
                    module_logger.error(
                        f"Error processing {parsed_url.url}: {str(e)}", exc_info=True)

    update_log(instance, f"🏁 Bulk process completed for '{os.path.basename(file_path)}'")


# ---------------------- GUI FUNCTIONS ----------------------

# * UI helper functions ---

def get_exe_dir():
    """Get the directory of the executable or script file."""
    return UtilityService.get_exe_dir()


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
        # Check if the Plex TV and movie libraries are configured
        if globals.plex.tv_libraries is None or globals.plex.movie_libraries is None:
            update_status(
                instance, "Plex setup incomplete. Please configure your settings.", color="warning")
            return

        # Process the URL and options passed from the GUI or website
        parsed_line = parse_url_and_options(url)

        # Update the UI before we start
        update_status(
            instance, f"Scraping: {parsed_line.url}", color="info", sticky=True, spinner=True)

        # Scrape the URL indicated, with the required options
        if TPBD_USER_BASE_PATH in parsed_line.url:
            scrape_tpdb_user(instance, parsed_line.url, parsed_line.options)
        else:
            success_counter = [0]
            title = scrape_and_upload(
                instance, parsed_line.url, parsed_line.options, success_counter)

        # And update the UI when we're done
        update_status(
            instance, f"Processed all artwork at {parsed_line.url}", color="success")

        # Update the web ui bulk list with this URL and artwork (only if it's not already in the bulk list)
        if instance.mode == "web" and parsed_line.options.add_to_bulk and title:
            notify_web(instance, "add_to_bulk_list",
                       {"url": url, "title": title})

    except ScraperException as scraping_error:
        update_status(instance, f"{scraping_error}", color="danger")

    finally:
        if instance.mode == "web":
            notify_web(instance, "element_disable",
                       {"element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False})


def run_bulk_import_scrape_in_thread(instance: Instance, web_list=None, filename=None, scheduled: bool = False):
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
        update_status(instance, "No valid bulk import entries found.",
                      color="danger")
        return

    if instance.mode == "web":
        notify_web(instance, "element_disable",
                   {"element": ["scrape_url", "scrape_button", "bulk_button"], "mode": True})

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
        scheduled:      Whether this was triggered by a scheduled job (for notification on completion).
    """

    # Track successful poster uploads (those with ✅ or ♻️)
    success_counter = [0]
    assets_processed = [0]
    errors = 0

    try:

        # Check if plex setup returned valid values
        if globals.plex.tv_libraries is None or globals.plex.movie_libraries is None:
            update_status(
                instance, "Plex setup incomplete. Please check the settings.", color="red")
            return

        # Log the start of the bulk import process
        display_filename = filename if filename else DEFAULT_BULK_IMPORT_FILE

        # Show the progress bar on the web UI
        notify_web(instance, "progress_bar", {"percent": 0})

        # Loop through the bulk list
        for i, parsed_line in enumerate(parsed_urls):

            notify_web(instance, "element_disable", {
                "element": ["bulk_button"], "mode": True})

            # Parse according to whether it's a user portfolio or poster / set URL
            if TPBD_USER_BASE_PATH in parsed_line.url:
                try:
                    scrape_tpdb_user(instance, parsed_line.url,
                                     parsed_line.options, success_counter, assets_processed)
                except Exception:
                    debug_me(f"Failed to scrape TPDb user URL: {parsed_line.url}", "process_bulk_import_from_ui")
                    pass
            else:
                try:
                    scrape_and_upload(instance, parsed_line.url,
                                      parsed_line.options, success_counter, assets_processed)
                except ScraperException as e:
                    update_log(instance, f"❌ Error processing line: '{parsed_line.url}'")
                    debug_me(f"ScraperException: Failed to scrape URL: {parsed_line.url} | {str(e)}", "process_bulk_import_from_ui")
                    errors += 1
                    pass

            percent = ((i + 1) / len(parsed_urls)) * 100
            notify_web(instance, "progress_bar",
                       {"message": f"{i + 1} / {len(parsed_urls)} ({percent.__round__()}%)", "percent": percent})

        # All done, update the UI
        notify_web(instance, "progress_bar",
                   {"message": f"{len(parsed_urls)} of {len(parsed_urls)} (100%)", "percent": 100})

        # Log the completion of the bulk import process
        poster_count = success_counter[0]

        message = (
            ("🏁 " if errors == 0 else "⚠️ ")
            + ("Scheduled b" if scheduled else "B")
            + f"ulk import of '{display_filename}' completed "
            + ("successfully • " if errors == 0 else f"with {errors} error(s), check logs for details • ")
            + f"{assets_processed[0]} asset(s) processed • "
            + f"{poster_count} asset(s) updated"
            + (f" • {errors} error(s)" if errors > 0 else "")
        )

        update_status(instance, message[2:], color="success" if errors == 0 else "warning")
        update_log(instance, message)
        if scheduled:
            debug_me(f"Sending notifications to {len(globals.config.apprise_urls)} notification service(s).", "process_bulk_import_from_ui")
            send_notification(instance, message)

    except Exception as bulk_import_exception:
        notify_web(instance, "progress_bar", {"percent": 100})
        update_status(
            instance, f"Error during bulk import: {bulk_import_exception}", color="danger")

    finally:
        notify_web(instance, "element_disable",
                   {"element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False})


# Scrape all pages of a TPDb user's uploaded artwork
def scrape_tpdb_user(instance: Instance, url, options, success_counter=None, assets_processed=None):
    if "?" in url:
        cleaned_url = url.split("?")[0]
        url = cleaned_url

    try:
        user_scraper = ThePosterDBScraper(url)
        user_scraper.scrape_user_info()
        pages = user_scraper.user_pages
    except ScraperException as cannot_scrape:
        debug_me(str(cannot_scrape), "scrape_tpdb_user")
        raise

    try:
        for page in range(pages):
            page_url = f"{url}?section=uploads&page={page + 1}"
            scrape_and_upload(instance, page_url, options, success_counter, assets_processed)
    except Exception:
        raise ScraperException(f"Failed to process and upload from URL: {url}")


# Scraped the URL then uploads what it's scraped to Plex
def scrape_and_upload(instance: Instance, url, options, success_counter=None, assets_processed=None):
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

    callbacks = ProcessingCallbacks(
        on_status_update=status_callback,
        on_log_update=log_callback,
        success_counter=success_counter,
        assets_processed=assets_processed
    )

    # Use the service to do the actual work
    try:
        processor = ArtworkProcessor(globals.plex)
        return processor.scrape_and_process(url, options, callbacks)
    except PlexConnectorException as not_connected:
        debug_me(f"PlexConnectorException: {str(not_connected)}", "scrape_and_upload")
        update_status(instance, str(not_connected), "danger")
        raise
    except ScraperException as scraper_error:
        debug_me(f"ScraperException: {str(scraper_error)}", "scrape_and_upload")
        raise


def process_uploaded_artwork(instance: Instance, file_list, skipped, zip_title, zip_author, zip_source, options, filters, plex_title=None, plex_year=None):
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

    def progress_callback(current: int, total: int):
        percent = (current / total * 100) if total > 0 else 0
        message = f"{current} / {total} ({percent.__round__()}%)" if current > 0 else ""
        notify_web(instance, "progress_bar", {
            "message": message, "percent": percent})

    def debug_callback(message: str, context: str):
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
        force=True if "force" in options else False
    )
    processor = ArtworkProcessor(globals.plex)
    processor.process_uploaded_files(file_list, skipped, zip_title, zip_author, zip_source, opts, callbacks, override_title=plex_title)


# * Bulk import file I/O functions ---
def load_bulk_import_file(instance: Instance, filename=None):
    """Load the bulk import file into the text area."""
    try:
        # Get the current bulk_txt value from the config
        bulk_import_filename = filename if filename is not None else (
            config.bulk_txt if config and config.bulk_txt is not None else DEFAULT_BULK_IMPORT_FILE)

        # Check if file exists
        if not globals.bulk_file_service.file_exists(bulk_import_filename):
            if instance.mode == "cli":
                module_logger.error(
                    f"File does not exist: {bulk_import_filename}")
            if instance.mode == "web":
                update_status(
                    instance, f"File does not exist: {bulk_import_filename}")
            return

        # Read file using service
        content = globals.bulk_file_service.read_file(bulk_import_filename)

        if instance.mode == "web":
            notify_web(instance, "load_bulk_import",
                       {"loaded": True, "filename": bulk_import_filename, "bulk_import_text": content})

    except FileNotFoundError as e:
        debug_me(f"File not found: {str(e)}", "load_bulk_import_file")
        notify_web(instance, "load_bulk_import", {
            "loaded": False, "error": f"File not found: {str(e)}"})
    except Exception as e:
        debug_me(
            f"Error loading bulk import: {str(e)}", "load_bulk_import_file")
        module_logger.error(f"Error loading bulk import: {str(e)}", exc_info=True)
        notify_web(instance, "load_bulk_import", {
            "loaded": False, "error": str(e)})


def rename_bulk_import_file(instance: Instance, old_name, new_name):
    debug_me(f"Renaming from {old_name} to {new_name}",
             "rename_bulk_import_file")

    if old_name != new_name:
        try:
            globals.bulk_file_service.rename_file(old_name, new_name)
            notify_web(instance, "rename_bulk_file",
                       {"renamed": True, "old_filename": old_name, "new_filename": new_name})
            update_status(instance, f"Renamed to {new_name}", "success")
            update_log(instance, f"✏️ Renamed bulk import file from '{old_name}' to '{new_name}'")
        except Exception:
            notify_web(instance, "rename_bulk_file", {
                "renamed": False, "old_filename": old_name})
            update_status(instance, f"Could not rename {old_name}", "warning")
            update_log(instance, f"🔴 Could not rename bulk import file '{old_name}'")


def delete_bulk_import_file(instance: Instance, file_name):
    if file_name:
        try:
            globals.bulk_file_service.delete_file(file_name)
            notify_web(instance, "delete_bulk_file", {
                "deleted": True, "filename": file_name})
            update_status(instance, f"Deleted {file_name}", "success")
            update_log(instance, f"🗑️ Deleted bulk import file '{file_name}'")
        except Exception:
            notify_web(instance, "delete_bulk_file", {
                "deleted": False, "filename": file_name})
            update_status(instance, f"Could not delete {file_name}", "warning")
            update_log(instance, f"🔴 Could not delete bulk import file '{file_name}'")


def save_bulk_import_file(instance: Instance, contents=None, filename=None, now_load=None):
    """Save the bulk import text area content to a file relative to the executable location."""
    if contents:
        try:
            bulk_import_filename = filename if filename is not None else (
                config.bulk_txt if config and config.bulk_txt is not None else DEFAULT_BULK_IMPORT_FILE)

            debug_me(f"Saving {bulk_import_filename}", "save_bulk_import_file")

            globals.bulk_file_service.write_file(
                contents, bulk_import_filename)

            update_status(
                instance, message=f"Bulk import file {filename} saved", color="success")
            notify_web(instance, "save_bulk_import", {
                "saved": True, "now_load": now_load})
            update_log(instance, f"💾 Saved bulk import file '{bulk_import_filename}'")
        except Exception:
            update_status(
                instance, message="Error saving bulk import file", color="danger")
            notify_web(instance, "save_bulk_import", {
                "saved": False, "now_load": now_load})
            update_log(instance, f"🔴 Error saving bulk import file '{bulk_import_filename}'")


def check_for_bulk_import_file(instance: Instance):
    """Check if any .txt files exist in the bulk_imports folder before creating bulk_import.txt."""
    try:
        bulk_import_filename = config.bulk_txt if config and config.bulk_txt is not None else DEFAULT_BULK_IMPORT_FILE
        globals.bulk_file_service.ensure_default_file_exists(
            bulk_import_filename)
    except Exception:
        update_status(
            instance, message="Error creating bulk import file", color="danger")


def find_bulk_file(filename: str = None):
    """Find a bulk import file - returns full path if exists, None otherwise."""
    # Get the current bulk_txt value from the config
    bulk_import_filename = filename if filename is not None else (
        config.bulk_txt if config and config.bulk_txt is not None else DEFAULT_BULK_IMPORT_FILE)

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
    web_routes.start_web_server(
        web_app, DEFAULT_WEB_PORT, globals.debug, config.ip_binding)


def check_image_orientation(image_path):
    """Check image orientation using ImageService."""
    return ImageService.check_orientation(image_path)


def sort_key(item):
    """Sort key for artwork items - uses UtilityService."""
    return UtilityService.sort_key(item)

def add_file_to_schedule_thread(instance: Instance, filename):
    if instance:
        threading.Thread(target=process_bulk_file_on_schedule,
                         args=(instance, filename,)).start()


def process_bulk_file_on_schedule(instance: Instance, filename):
    instance.broadcast = True

    try:
        bulk_import_file = find_bulk_file(filename)
        if bulk_import_file:
            with open(bulk_import_file, "r", encoding="utf-8") as file:
                content = file.read()
            if content:
                update_log(instance, f"🕘 Scheduled bulk import started for '{filename}'")
                debug_me(f"Scheduled import started for instance {instance.id} mode {instance.mode}", "process_bulk_file_on_schedule")
                send_notification(instance, f"🕘 Scheduled bulk import started for '{filename}'")
                run_bulk_import_scrape_in_thread(instance, content, filename, scheduled=True)
        else:
            update_log(instance, f"🔴 Bulk file does not exist: {filename}")
            return
    except FileNotFoundError:
        update_log(
            instance, f"🔴 Scheduled bulk import failed due to missing file ({filename})")
    except Exception as e:
        update_log(
            instance, f"🔴 Scheduled bulk import unexpectedly failed ({str(e)})")


# Legacy functions - now handled by SchedulerService
# Kept for backwards compatibility but no longer used internally


# Initialises the scheduler when the script is run
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
            debug_me("Scheduler started.", "setup_scheduler_on_first_load")

        debug_me(globals.config.schedules, "setup_scheduler_on_first_load")


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
    filename_pattern = re.compile(
        r'^[^/]+(?:\.jpg|\.jpeg|\.png)$', re.IGNORECASE)

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
                          filters=args.filters,
                          exclude=args.exclude,
                          year=args.year,
                          kometa=args.kometa,
                          stage=args.stage,
                          temp=args.temp)  # Arguments per url to process

    # Determine config path: environment variable (for Docker) takes precedence over CLI argument
    config_path = os.environ.get("CONFIG_PATH", args.config)
    if not config_path:
        config_path = DEFAULT_CONFIG_PATH

    # Create config as a global object
    config = Config(config_path=config_path)
    globals.config = config  # Also store in globals for cross-module access

    # Load the config from the config.json file
    # Note: We use logger.debug here since logging is not yet fully configured
    module_logger.debug(f"Attempting to load config from: {config_path}")
    module_logger.debug(f"Config file exists: {os.path.isfile(config_path)}")
    module_logger.debug(f"Current working directory: {os.getcwd()}")
    module_logger.debug(f"Config path is absolute: {os.path.isabs(config_path)}")

    try:
        config.load()
        module_logger.debug(f"Config loaded successfully from {config_path}")
    except ConfigLoadError as e:
        module_logger.error(f"ConfigLoadError: {str(e)}")
        traceback.print_exc()
        sys.exit(
            "Can't load config.json file.  Please check that the file exists and is in the correct format.")
    except Exception as config_load_exception:
        module_logger.error(
            f"Unexpected error when loading config.json file: {str(config_load_exception)}")
        traceback.print_exc()
        sys.exit(
            f"Unexpected error when loading config.json file: {str(config_load_exception)}")

    # Determine log directory: environment variable (for Docker) takes precedence over CLI argument
    logs_dir = os.environ.get("LOGS_DIR", args.logs)
    if not logs_dir:
        logs_dir = DEFAULT_LOGS_DIR

    # Initialize logging with debug flag from config or CLI args
    debug_mode = args.debug or config.debug
    logger = setup_logging(debug=debug_mode, log_dir=logs_dir)
    logger.info(
        f"Logging initialized (debug={'enabled' if debug_mode else 'disabled'}, log_dir={logs_dir})")

    # Create services
    # Initialize bulk file service with optional custom path from environment variable
    bulk_imports_dir = os.environ.get("BULK_IMPORTS_DIR")
    globals.bulk_file_service = BulkFileService(
        base_dir=get_exe_dir(),
        bulk_imports_dir=bulk_imports_dir
    )
    globals.scheduler_service = SchedulerService(
        check_interval=SCHEDULER_CHECK_INTERVAL)

    # Make sure there's at least one bulk_import file
    check_for_bulk_import_file(cli_instance)

    # Create a connector for Plex
    globals.plex = PlexConnector(config.base_url, config.token)

    # Check for CLI arguments regardless of interactive_cli flag
    if cli_command:

        # Setup scheduler
        setup_scheduler_on_first_load(cli_instance)

        # Connect to the TV and Movie libraries
        try:
            globals.plex.set_tv_libraries(config.tv_library)
        except PlexConnectorException as e:
            token_display = f"{config.token[:10]}..." if config.token else "(not set)"
            logger.error(
                f"{'=' * 70}\n"
                f"ERROR: Could not connect to Plex server\n"
                f"{'=' * 70}\n"
                f"{e}\n\n"
                f"Please check your config.json settings:\n"
                f"  - base_url: {config.base_url}\n"
                f"  - token: {token_display}\n\n"
                f"Ensure your Plex server is running and accessible.\n"
                f"{'=' * 70}", exc_info=True
            )
            sys.exit(1)

        try:
            globals.plex.set_movie_libraries(config.movie_library)
        except PlexConnectorException as e:
            logger.error(
                f"{'=' * 70}\n"
                f"ERROR: Could not connect to Plex movie libraries\n"
                f"{'=' * 70}\n"
                f"{e}\n"
                f"{'=' * 70}", exc_info=True
            )
            sys.exit(1)

        # Handle the CLI options if we're not using the web ui
        if cli_command == 'bulk':

            # Remove some of the command line options which should be specified per line
            cli_options.add_posters = False
            cli_options.add_sets = False
            cli_options.year = None
            cli_options.clear_filters()

            # Process using the bulk filename if supplied, else the bulk file set in the config
            default_bulk_file = globals.bulk_file_service.get_bulk_file_path(
                config.bulk_txt)
            parse_bulk_file_from_cli(
                cli_instance, args.bulk_file if args.bulk_file else default_bulk_file)

        # Now we're looking at URLs - firstly one containing a TPDb user
        elif TPBD_USER_BASE_PATH in cli_command:

            # Remove some of the command line options which aren't applicable to user scraping
            cli_options.year = None
            cli_options.add_posters = False
            cli_options.add_sets = False
            try:
                scrape_tpdb_user(cli_instance, cli_command, cli_options)
            except Exception as e:
                debug_me(f"Error scraping user: {str(e)}", "__main__")
                logger.error(
                    f"Error scraping TPDb user: {str(e)}",
                    exc_info=True
                )

        # User passed in a poster or set URL, so let's process that
        else:
            try:
                success_counter = [0]
                scrape_and_upload(cli_instance, cli_command, cli_options, success_counter)
            except Exception as e:
                update_status(cli_instance, str(e), color="danger")
    else:

        # If no CLI arguments, proceed with UI creation (if not in interactive CLI mode)
        if not interactive_cli:

            update_log(cli_instance, f"🚀 Starting Artwork Uploader {CURRENT_VERSION} in web mode")
            if globals.docker:
                update_log(cli_instance, "🐳 Running in Docker environment", force_print=True)

            # Setup scheduler only in the main process to avoid duplication
            if os.getenv("WERKZEUG_RUN_MAIN") == "true" or not globals.debug:
                update_log(cli_instance, "🗓️ Setting up scheduler for scheduled tasks")
                debug_me("This is the main process - setting up scheduler", "__main__")
                setup_scheduler_on_first_load(cli_instance)
            else:
                debug_me("Not the main process - skipping scheduler setup", "__main__")
                update_log(cli_instance, "⚠️ Skipping scheduler setup in debug mode")

            # Connect to the TV and Movie libraries
            plex_connected = True
            try:
                globals.plex.set_tv_libraries(config.tv_library)
            except PlexConnectorException as e:
                logger.warning(
                    f"{'=' * 70}\n"
                    f"WARNING: Could not connect to Plex TV libraries\n"
                    f"{'=' * 70}\n"
                    f"{e}\n\n"
                    f"The web UI will still start, but you won't be able to upload artwork\n"
                    f"until you fix the Plex connection in Settings.\n"
                )
                plex_connected = False

            try:
                globals.plex.set_movie_libraries(config.movie_library)
            except PlexConnectorException as e:
                if plex_connected:  # Only log if we didn't already log for TV
                    logger.warning(
                        f"{'=' * 70}\n"
                        f"WARNING: Could not connect to Plex Movie libraries\n"
                        f"{'=' * 70}\n"
                        f"{e}\n\n"
                        f"The web UI will still start, but you won't be able to upload artwork\n"
                        f"until you fix the Plex connection in Settings.\n"
                    )

            # Create the app and web server

            web_app = Flask(__name__, template_folder="templates")

            # Enable CORS for all routes to allow Socket.IO connections from any origin
            CORS(web_app, resources={r"/*": {"origins": "*", "supports_credentials": True}})

            # Configure session for authentication
            import secrets
            from datetime import timedelta

            web_app.config['SECRET_KEY'] = secrets.token_hex(32)
            web_app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

            # Configure SocketIO with increased timeouts for large file uploads
            # ping_timeout: How long to wait for a pong response before disconnecting (default: 60s)
            # ping_interval: How often to send pings to keep connection alive (default: 25s)
            # http_compression: Enable compression for better performance with large uploads
            # max_http_buffer_size: Maximum size of HTTP long-polling messages (default: 1MB)
            globals.web_socket = SocketIO(
                web_app,
                cors_allowed_origins="*",
                async_mode="eventlet",
                ping_timeout=300,  # 5 minutes - allows time for large file processing
                ping_interval=25,  # Keep default 25s to maintain connection health
                http_compression=True,  # Enable compression for better performance
                max_http_buffer_size=10000000  # 10MB - allow larger individual messages
            )

            setup_web_sockets()
