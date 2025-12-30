import os
import re
import sys
import threading
import traceback
import uuid

import eventlet

from core import globals
from core.config import Config
from core.constants import (
    CURRENT_VERSION,
    GITHUB_REPO,
    DEFAULT_BULK_IMPORT_FILE,
    DEFAULT_CONFIG_PATH,
    DEFAULT_WEB_PORT,
    SCHEDULER_CHECK_INTERVAL,
    UPDATE_CHECK_INTERVAL,
    MIN_PYTHON_MAJOR,
    MIN_PYTHON_MINOR, TPBD_USER_BASE_PATH
)
from core.enums import InstanceMode
from core.exceptions import ConfigLoadError, PlexConnectorException, ScraperException
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
    UpdateService,
    UtilityService
)
from utils.notifications import update_log, update_status, notify_web, debug_me
from utils.utils import is_not_comment, parse_url_and_options

eventlet.monkey_patch()

# Module logger - will be properly configured after config is loaded
module_logger = None

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

    # Loop through the file, process the URL and options, then scrape according to the URL
    for line in urls:

        # Skip comments
        if is_not_comment(line):

            # Parse the line to extract the URL and options
            parsed_url = parse_url_and_options(line)

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
                    scrape_and_upload(
                        instance, parsed_url.url, parsed_url.options)
                except Exception as e:
                    module_logger.error(
                        f"Error processing {parsed_url.url}: {str(e)}", exc_info=True)


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
            title = scrape_and_upload(
                instance, parsed_line.url, parsed_line.options)

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


def run_bulk_import_scrape_in_thread(instance: Instance, web_list=None, filename=None):
    """Run the bulk import scrape in a separate thread."""

    parsed_urls = []

    # Grab the one from the web interface
    bulk_import_list = web_list.strip().split("\n")

    # Loop through the import file and build a list of URLs and options
    # Ignoring any lines containing comments using # or //
    for line in bulk_import_list:
        if is_not_comment(line):
            parsed_url = parse_url_and_options(line)
            parsed_urls.append(parsed_url)

    if not parsed_urls:
        update_status(instance, "No bulk import entries found.",
                      color="danger")

    if instance.mode == "web":
        notify_web(instance, "element_disable",
                   {"element": ["scrape_url", "scrape_button", "bulk_button"], "mode": True})

    # Pass the processing of the parsed URLs off to a thread
    if instance.mode == "web":
        process_bulk_import_from_ui(instance, parsed_urls, filename)


def process_bulk_import_from_ui(instance: Instance, parsed_urls: list, filename: str = None) -> None:
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

    try:

        # Check if plex setup returned valid values
        if globals.plex.tv_libraries is None or globals.plex.movie_libraries is None:
            update_status(
                instance, "Plex setup incomplete. Please check the settings.", color="red")
            return

        # Log the start of the bulk import process
        display_filename = filename if filename else DEFAULT_BULK_IMPORT_FILE
        update_log(instance, f"🎬 Bulk process started - {display_filename}")

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
                                     parsed_line.options, success_counter)
                except Exception:
                    pass
            else:
                try:
                    scrape_and_upload(instance, parsed_line.url,
                                      parsed_line.options, success_counter)
                except Exception:
                    pass

            percent = ((i + 1) / len(parsed_urls)) * 100
            notify_web(instance, "progress_bar",
                       {"message": f"{i + 1} / {len(parsed_urls)} ({percent.__round__()}%)", "percent": percent})

        # All done, update the UI
        notify_web(instance, "progress_bar",
                   {"message": f"{len(parsed_urls)} of {len(parsed_urls)} (100%)", "percent": 100})
        update_status(
            instance, "Bulk import scraping completed.", color="success")

        # Log the completion of the bulk import process
        poster_count = success_counter[0]
        update_log(
            instance, f"🏁 Bulk process completed - {display_filename} - {poster_count} assets updated")

    except Exception as bulk_import_exception:
        notify_web(instance, "progress_bar", {"percent": 100})
        update_status(
            instance, f"Error during bulk import: {bulk_import_exception}", color="danger")

    finally:
        notify_web(instance, "element_disable",
                   {"element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False})


# Scrape all pages of a TPDb user's uploaded artwork
def scrape_tpdb_user(instance: Instance, url, options, success_counter=None):
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
            scrape_and_upload(instance, page_url, options, success_counter)
    except Exception:
        raise ScraperException(f"Failed to process and upload from URL: {url}")


# Scraped the URL then uploads what it's scraped to Plex
def scrape_and_upload(instance: Instance, url, options, success_counter=None):
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
        success_counter=success_counter
    )

    # Use the service to do the actual work
    try:
        processor = ArtworkProcessor(globals.plex)
        return processor.scrape_and_process(url, options, callbacks)
    except PlexConnectorException as not_connected:
        update_status(instance, str(not_connected), "danger")
        raise


def process_uploaded_artwork(instance: Instance, file_list, options, filters, plex_title=None, plex_year=None):
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
    if plex_year:
        plex_year = int(plex_year)
        opts = Options(filters=filters, year=plex_year, temp=True if "temp" in options else False,
                       stage=True if "stage" in options else False, force=True if "force" in options else False)
    else:
        opts = Options(filters=filters, temp=True if "temp" in options else False,
                       stage=True if "stage" in options else False, force=True if "force" in options else False)
    processor = ArtworkProcessor(globals.plex)
    processor.process_uploaded_files(
        file_list, opts, callbacks, override_title=plex_title)


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
        import traceback
        traceback.print_exc()
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
        except Exception:
            notify_web(instance, "rename_bulk_file", {
                "renamed": False, "old_filename": old_name})
            update_status(instance, f"Could not rename {old_name}", "warning")


def delete_bulk_import_file(instance: Instance, file_name):
    if file_name:
        try:
            globals.bulk_file_service.delete_file(file_name)
            notify_web(instance, "delete_bulk_file", {
                "deleted": True, "filename": file_name})
            update_status(instance, f"Deleted {file_name}", "success")
        except Exception:
            notify_web(instance, "delete_bulk_file", {
                "deleted": False, "filename": file_name})
            update_status(instance, f"Could not delete {file_name}", "warning")


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
        except Exception:
            update_status(
                instance, message="Error saving bulk import file", color="danger")
            notify_web(instance, "save_bulk_import", {
                "saved": False, "now_load": now_load})


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
                update_log(instance, "@ *** Scheduled import started ***")
                run_bulk_import_scrape_in_thread(instance, content, filename)
        else:
            update_log(instance, f"Scheduled file does not exist: {filename}")
            return
    except FileNotFoundError:
        update_log(
            instance, f"@ Scheduled import failed due to missing file ({filename})")
    except Exception as e:
        update_log(
            instance, f"@ Scheduled import unexpectedly failed ({str(e)})")


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
    # Note: We use print here since logging is not yet configured
    print(f"[DEBUG] Attempting to load config from: {config_path}")
    print(f"[DEBUG] Config file exists: {os.path.isfile(config_path)}")
    print(f"[DEBUG] Current working directory: {os.getcwd()}")
    print(f"[DEBUG] Config path is absolute: {os.path.isabs(config_path)}")

    try:
        config.load()
        print(f"[DEBUG] Config loaded successfully from {config_path}")
    except ConfigLoadError as e:
        print(f"[ERROR] ConfigLoadError: {str(e)}")
        print("[ERROR] Stack trace:")
        traceback.print_exc()
        sys.exit(
            "Can't load config.json file.  Please check that the file exists and is in the correct format.")
    except Exception as config_load_exception:
        print(
            f"[ERROR] Unexpected error when loading config.json file: {str(config_load_exception)}")
        print("[ERROR] Stack trace:")
        traceback.print_exc()
        sys.exit(
            f"Unexpected error when loading config.json file: {str(config_load_exception)}")

    # Initialize logging with debug flag from config or CLI args
    debug_mode = args.debug or config.debug
    logger = setup_logging(debug=debug_mode)
    logger.info(
        f"Logging initialized (debug={'enabled' if debug_mode else 'disabled'})")

    # Set module logger for use in functions
    global module_logger
    module_logger = get_logger(__name__)

    # Create services
    # Initialize bulk file service with optional custom path from environment variable
    bulk_imports_dir = os.environ.get("BULK_IMPORTS_DIR")
    globals.bulk_file_service = BulkFileService(
        base_dir=get_exe_dir(),
        bulk_imports_dir=bulk_imports_dir
    )
    globals.scheduler_service = SchedulerService(
        check_interval=SCHEDULER_CHECK_INTERVAL)
    globals.update_service = UpdateService(
        github_repo=GITHUB_REPO,
        current_version=current_version,
        check_interval=UPDATE_CHECK_INTERVAL
    )

    # Make sure there's at least one bulk_import file
    check_for_bulk_import_file(cli_instance)

    # Create a connector for Plex
    globals.plex = PlexConnector(config.base_url, config.token)

    # Setup scheduler
    setup_scheduler_on_first_load(cli_instance)

    # Check for CLI arguments regardless of interactive_cli flag
    if cli_command:

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
                scrape_and_upload(cli_instance, cli_command, cli_options)
            except Exception as e:
                update_status(cli_instance, str(e), color="danger")
    else:

        # If no CLI arguments, proceed with UI creation (if not in interactive CLI mode)
        if not interactive_cli:

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

            # Configure session for authentication
            import secrets
            from datetime import timedelta

            web_app.config['SECRET_KEY'] = secrets.token_hex(32)
            web_app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

            globals.web_socket = SocketIO(
                web_app, cors_allowed_origins="*", async_mode="eventlet")

            # Start update checker using UpdateService

            def on_update_available(version: str):
                debug_me(
                    f"Update available. Latest version: {version}", "update_service")
                notify_web(Instance(broadcast=True),
                           "update_available", {"version": version})

            globals.update_service.start_periodic_check(on_update_available)

            setup_web_sockets()
