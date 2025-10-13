import eventlet
eventlet.monkey_patch()

import base64
from pathlib import Path

import uuid
import os
import re
import zipfile
import tempfile

import requests
import subprocess
import schedule, time
import globals
import threading
import sys

import utils
import arguments
from instance import Instance
from media_metadata import parse_title
from notifications import update_log, update_status, notify_web, debug_me
from config import Config
from exceptions import ConfigLoadError, PlexConnectorException, ScraperException
from theposterdb_scraper import ThePosterDBScraper
from upload_processor import UploadProcessor
from scraper import Scraper
from utils import is_not_comment, parse_url_and_options
from options import Options
from plex_connector import PlexConnector
from exceptions import CollectionNotFound, MovieNotFound, ShowNotFound, NotProcessedByFilter, \
    NotProcessedByExclusion
from constants import (
    CURRENT_VERSION,
    GITHUB_REPO,
    DEFAULT_WEB_PORT,
    DEFAULT_WEB_HOST,
    SCHEDULER_CHECK_INTERVAL,
    UPDATE_CHECK_INTERVAL,
    MIN_PYTHON_MAJOR,
    MIN_PYTHON_MINOR
)
from enums import InstanceMode, ScraperSource
from services import (
    BulkFileService,
    ImageService,
    ArtworkProcessor,
    ProcessingCallbacks,
    SchedulerService,
    UpdateService,
    UtilityService
)

# ----------------------------------------------
# Important for autoupdater
current_version = CURRENT_VERSION
# ----------------------------------------------

if sys.version_info[0] != MIN_PYTHON_MAJOR or sys.version_info[1] < MIN_PYTHON_MINOR:
    print(f"Version: {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]} is not compatible with Artwork Uploader, please upgrade to Python {MIN_PYTHON_MAJOR}.{MIN_PYTHON_MINOR}+")
    sys.exit(0)

try:
    from PIL import Image
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



# ! Interactive CLI mode flag
interactive_cli = False  # Set to False when building the executable with PyInstaller for it launches the web UI by default
mode = InstanceMode.CLI.value
scheduled_jobs = {}  # Legacy - kept for backwards compatibility
scheduled_jobs_by_file = {}  # Legacy - kept for backwards compatibility
bulk_file_service = None  # Initialized in main
scheduler_service = None  # Initialized in main
update_service = None  # Initialized in main


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
        print("File not found. Please enter a valid file path.")

    # Loop through the file, process the URL and options, then scrape according to the URL
    for line in urls:

        # Skip comments
        if is_not_comment(line):

            # Parse the line to extract the URL and options
            parsed_url = parse_url_and_options(line)

            # Parse according to whether it's a user portfolio or poster / set URL
            if "/user/" in parsed_url.url:
                try:
                    scrape_tpdb_user(instance, parsed_url.url, parsed_url.options)
                except ScraperException as scraper_error:
                    print(str(scraper_error))
                except Exception as unknown_error:
                    print(str(unknown_error))
            else:
                try:
                    scrape_and_upload(instance, parsed_url.url, parsed_url.options)
                except Exception as e:
                    print(f"Error processing {parsed_url.url}: {str(e)}")


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
            update_status(instance, "Plex setup incomplete. Please configure your settings.", color="warning")
            return

        # Process the URL and options passed from the GUI or website
        parsed_line = parse_url_and_options(url)

        # Update the UI before we start
        update_status(instance, f"Scraping: {parsed_line.url}", color="info", sticky=True, spinner=True)

        # Scrape the URL indicated, with the required options
        if "/user/" in parsed_line.url:
            scrape_tpdb_user(instance, parsed_line.url, parsed_line.options)
        else:
            title = scrape_and_upload(instance, parsed_line.url, parsed_line.options)

        # And update the UI when we're done
        update_status(instance, f"Processed all artwork at {parsed_line.url}", color="success")

        # Update the web ui bulk list with this URL and artwork (only if it's not already in the bulk list)
        if instance.mode == "web" and parsed_line.options.add_to_bulk and title:
            notify_web(instance, "add_to_bulk_list", {"url": url, "title": title})

    except ScraperException as scraping_error:
        update_status(instance, f"{scraping_error}", color="danger")

    finally:
        if instance.mode == "web":
            notify_web(instance, "element_disable", {"element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False})


def run_bulk_import_scrape_in_thread(instance: Instance, web_list = None):

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
        update_status(instance, "No bulk import entries found.", color="danger")

    if instance.mode == "web":
        notify_web(instance, "element_disable", {"element": ["scrape_url", "scrape_button", "bulk_button"], "mode": True})

    # Pass the processing of the parsed URLs off to a thread
    if instance.mode == "web":
        try:
            process_bulk_import_from_ui(instance, parsed_urls)
        except Exception:
            raise


def process_bulk_import_from_ui(instance: Instance, parsed_urls: list) -> None:

    """
    Process the bulk import scrape, based on the contents of the Bulk Import tab in the GUI.

    The bulk import list doesn't need to have been saved, it will use the list as it exists in the GUI currently.

    Args:
        instance:
        parsed_urls:    The URLs to scrape.  These can be theposterdb poster, set or user URL or a mediux set URL.
    """

    try:

        # Check if plex setup returned valid values
        if globals.plex.tv_libraries is None or globals.plex.movie_libraries is None:
            update_status(instance, "Plex setup incomplete. Please check the settings.", color="red")
            return

        # Show the progress bar on the web UI
        notify_web(instance, "progress_bar", {"percent" : 0})

        # Loop through the bulk list
        for i, parsed_line in enumerate(parsed_urls):

            notify_web(instance, "element_disable", {"element": ["bulk_button"], "mode": True})

            # Parse according to whether it's a user portfolio or poster / set URL
            if "/user/" in parsed_line.url:
                scrape_tpdb_user(instance, parsed_line.url, parsed_line.options)
            else:
                scrape_and_upload(instance, parsed_line.url, parsed_line.options)

            notify_web(instance, "progress_bar", {"message": f"{i + 1} of {len(parsed_urls)}", "percent" : ((i + 1) / len(parsed_urls)) * 100})

        # All done, update the UI
        notify_web(instance, "progress_bar", {"message": f"{len(parsed_urls)} of {len(parsed_urls)}", "percent" : 100})
        update_status(instance, "Bulk import scraping completed.", color="success")

    except Exception as bulk_import_exception:
        notify_web(instance, "progress_bar", {"percent": 100})
        update_status(instance, f"Error during bulk import: {bulk_import_exception}", color="danger")

    finally:
        notify_web(instance, "element_disable", {"element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False})


# Scrape all pages of a TPDb user's uploaded artwork
def scrape_tpdb_user(instance: Instance, url, options):

    if "?" in url:
        cleaned_url = url.split("?")[0]
        url = cleaned_url

    try:
        user_scraper = ThePosterDBScraper(url)
        user_scraper.scrape_user_info()
        pages = user_scraper.user_pages
    except ScraperException as cannot_scrape:
        debug_me(str(cannot_scrape),"scrape_tpdb_user")
        raise

    try:
        for page in range(pages):
            page_url = f"{url}?section=uploads&page={page + 1}"
            scrape_and_upload(instance, page_url, options)
    except Exception:
        raise ScraperException(f"Failed to process and upload from URL: {url}")


# Scraped the URL then uploads what it's scraped to Plex
def scrape_and_upload(instance: Instance, url, options):
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
        on_log_update=log_callback
    )

    # Use the service to do the actual work
    try:
        processor = ArtworkProcessor(globals.plex)
        return processor.scrape_and_process(url, options, callbacks)
    except PlexConnectorException as not_connected:
        update_status(instance, str(not_connected), "danger")
        raise


def process_uploaded_artwork(instance: Instance, file_list, filters, plex_title = None, plex_year = None):
    """
    Process uploaded artwork files and upload to Plex.

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
        message = f"{current} of {total}" if current > 0 else ""
        notify_web(instance, "progress_bar", {"message": message, "percent": percent})

    def debug_callback(message: str, context: str):
        debug_me(message, context)

    callbacks = ProcessingCallbacks(
        on_status_update=status_callback,
        on_log_update=log_callback,
        on_progress_update=progress_callback,
        on_debug=debug_callback
    )

    # Use the service to do the actual work
    options = Options(filters=filters, year=plex_year)
    processor = ArtworkProcessor(globals.plex)
    processor.process_uploaded_files(file_list, options, callbacks, override_title=plex_title)


# * Bulk import file I/O functions ---
def load_bulk_import_file(instance: Instance, filename = None):
    """Load the bulk import file into the text area."""
    global config

    try:
        # Get the current bulk_txt value from the config
        bulk_import_filename = filename if filename is not None else config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt"

        # Check if file exists
        if not bulk_file_service.file_exists(bulk_import_filename):
            if instance.mode == "cli":
                print(f"File does not exist: {bulk_import_filename}")
            if instance.mode == "web":
                update_status(instance, f"File does not exist: {bulk_import_filename}")
            return

        # Read file using service
        content = bulk_file_service.read_file(bulk_import_filename)

        if instance.mode == "web":
            notify_web(instance, "load_bulk_import", {"loaded": True, "filename": bulk_import_filename, "bulk_import_text": content})

    except FileNotFoundError:
        notify_web(instance, "load_bulk_import", {"loaded": False})
    except Exception as e:
        notify_web(instance, "load_bulk_import", {"loaded": False})


def rename_bulk_import_file(instance: Instance, old_name, new_name):
    debug_me(f"Renaming from {old_name} to {new_name}", "rename_bulk_import_file")

    if old_name != new_name:
        try:
            bulk_file_service.rename_file(old_name, new_name)
            notify_web(instance, "rename_bulk_file", {"renamed": True, "old_filename": old_name, "new_filename": new_name})
            update_status(instance, f"Renamed to {new_name}", "success")
        except Exception as e:
            notify_web(instance, "rename_bulk_file", {"renamed": False, "old_filename": old_name})
            update_status(instance, f"Could not rename {old_name}", "warning")


def delete_bulk_import_file(instance: Instance, file_name):
    if file_name:
        try:
            bulk_file_service.delete_file(file_name)
            notify_web(instance, "delete_bulk_file", {"deleted": True, "filename": file_name})
            update_status(instance, f"Deleted {file_name}", "success")
        except Exception as e:
            notify_web(instance, "delete_bulk_file", {"deleted": False, "filename": file_name})
            update_status(instance, f"Could not delete {file_name}", "warning")


def save_bulk_import_file(instance: Instance, contents = None, filename = None, now_load = None):
    """Save the bulk import text area content to a file relative to the executable location."""
    if contents:
        try:
            bulk_import_filename = filename if filename is not None else config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt"

            debug_me(f"Saving {bulk_import_filename}", "save_bulk_import_file")

            bulk_file_service.write_file(contents, bulk_import_filename)

            update_status(instance, message=f"Bulk import file {filename} saved", color="success")
            notify_web(instance, "save_bulk_import", {"saved": True, "now_load": now_load})
        except Exception as e:
            update_status(instance, message="Error saving bulk import file", color="danger")
            notify_web(instance, "save_bulk_import", {"saved": False, "now_load": now_load})


def check_for_bulk_import_file(instance: Instance):
    """Check if any .txt files exist in the bulk_imports folder before creating bulk_import.txt."""
    try:
        bulk_import_filename = config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt"
        bulk_file_service.ensure_default_file_exists(bulk_import_filename)
    except Exception as e:
        update_status(instance, message="Error creating bulk import file", color="danger")


def find_bulk_file(filename: str = None):
    """Find a bulk import file - returns full path if exists, None otherwise."""
    # Get the current bulk_txt value from the config
    bulk_import_filename = filename if filename is not None else config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt"

    # Use the service to check if file exists
    if bulk_file_service.file_exists(bulk_import_filename):
        return bulk_file_service.get_bulk_file_path(bulk_import_filename)
    return None


def setup_web_sockets():

    @web_app.route("/")
    def home():
        return render_template("web_interface.html", config=config)




    @globals.web_socket.on("check_for_update")
    def check_for_update(data):
        """Check for updates when requested by the frontend."""
        instance = Instance(data.get("instance_id"), "web")
        latest_version = get_latest_version()
        if latest_version and latest_version != current_version:
            notify_web(instance, "update_available", {"version": latest_version})

    @globals.web_socket.on("update_app")
    def update_app(data):
        instance = Instance(data.get("instance_id"), "web")

        """
        Pull updates from GitHub and restart the app.
        """

        try:
            update_status(Instance(broadcast=True),"Updating to the latest version, please wait...","info", sticky=True, spinner=True)

            # Detect platform
            python_cmd = "python3" if sys.platform == "darwin" else "python"

            # Pull latest changes
            subprocess.run(["git", "pull"], check=True)

            # Install dependencies
            subprocess.run([python_cmd, "-m", "pip", "install", "-r", "requirements.txt"], check=True)

            # Trigger the front-end to restart
            update_status(Instance(broadcast=True),"Update complete, restarting the app...","success", sticky=True, spinner=True)
            notify_web(Instance(broadcast=True), "backend_restarting",{})

            # Restart the app
            os.execlp(python_cmd, python_cmd, "artwork_uploader.py")

        except Exception as e:
            update_status(Instance(broadcast=True),"Update failed, restarting the app...","danger")
            notify_web(instance,"update_failed", {"error": str(e)})


    @globals.web_socket.on("start_scrape")
    def handle_scrape_from_web(data):
        
        instance = Instance(data.get("instance_id"),"web")
        url = data.get("url").lower()
        options = data.get("options")
        filters = data.get("filters")
        year = data.get("year")

        if url:
            if year:
                url = url + f" --year {year}"
            if options:
                url = url + " " + " ".join(options)
            if filters and len(filters) < 6:
                url = url + " --filters " + " ".join(filters)
            notify_web(instance, "element_disable", {"element": ["scrape_url", "scrape_button", "bulk_button"], "mode": True})
            process_scrape_url_from_web(instance, url)

    @globals.web_socket.on("start_bulk_import")
    def handle_bulk_import_from_web(data):
        
        instance = Instance(data.get("instance_id"),"web")
        bulk_list = data.get("bulk_list").lower()
        run_bulk_import_scrape_in_thread(instance, bulk_list)


    @globals.web_socket.on("save_bulk_import")
    def handle_bulk_import(data):
        instance = Instance(data.get("instance_id"),"web")
        content = data.get("content")
        filename = data.get("filename")
        now_load = data.get("now_load")
        if content:
            save_bulk_import_file(instance, content, filename, now_load)

    @globals.web_socket.on("load_config")
    def load_config_web(data):
        global config
        instance = Instance(data.get("instance_id"), "web")
        config.load()
        update_scheduled_jobs()
        notify_web(instance, "load_config", {"config": vars(config)} )

    @globals.web_socket.on("load_bulk_filelist")
    def load_bulk_filelist(data):
        instance = Instance(data.get("instance_id"),"web")
        bulk_files = None
        try:
            folder_path = Path("bulk_imports")
            bulk_files = [f.name for f in folder_path.iterdir() if f.is_file()]
        except (FileNotFoundError, PermissionError) as e:
            debug_me(f"Error loading bulk file list: {e}", "load_bulk_filelist")
            pass
        notify_web(instance, "load_bulk_filelist",{"bulk_files": bulk_files})


    @globals.web_socket.on("load_bulk_import")
    def load_bulk_import(data):
        global config
        instance = Instance(data.get("instance_id"),"web")
        load_bulk_import_file(instance, data.get("filename"))

    @globals.web_socket.on("rename_bulk_file")
    def rename_bulk_file(data):
        instance = Instance(data.get("instance_id"),"web")
        rename_bulk_import_file(instance, data.get("old_filename"), data.get("new_filename"))

    @globals.web_socket.on("delete_bulk_file")
    def delete_bulk_file(data):
        instance = Instance(data.get("instance_id"),"web")
        delete_bulk_import_file(instance, data.get("filename"))

    @globals.web_socket.on("display_message")
    def display_message(data):
        debug_me(data.get("message"),"display_message")

    @globals.web_socket.on("save_config")
    def save_config_web(data):

        global config
        instance = Instance(data.get("instance_id"),"web")

        try:
            # Unpack the config dictionary into the local config
            for key, value in data.get("config").items():
                setattr(config, key, value)
            config.save()

            # Reconnect to Plex because the Plex server or token might have changed
            update_log(instance, "Saving updated configuration and reconnecting to Plex")
            globals.plex.reconnect(config)
            notify_web(instance, "save_config",{"saved":True, "config": vars(config)})
        except Exception as config_error:
            update_status(instance, str(config_error), color="danger")

    @globals.web_socket.on("delete_schedule")
    def delete_task_from_scheduler(data):

        if data.get("instance_id"):
            instance = Instance(data.get("instance_id"),"web")
            schedule_file = data.get("file")

            if schedule_file:
                try:
                    job_id = scheduled_jobs_by_file[schedule_file]
                except KeyError:
                    job_id = None

                if job_id:

                    # Cancel the scheduled job and delete it from the job list
                    schedule.cancel_job(scheduled_jobs[job_id])
                    del scheduled_jobs[job_id]

                    # Make sure it's also removed from the config file
                    config.load()
                    config.schedules = [each_schedule for each_schedule in config.schedules if each_schedule["file"] != schedule_file]
                    config.save()

                    # And update the front-end
                    notify_web(instance, "delete_schedule", {"file": schedule_file, "job_reference": job_id, "deleted": True})
                else:
                    notify_web(instance,"delete_schedule", {"deleted": False, "job_id": job_id})


    @globals.web_socket.on("add_schedule")
    def add_tasks_to_scheduler(data):
        try:
            # Schedule bulk import task
            if data.get("instance_id"):
                instance = Instance(data.get("instance_id"),"web")
                schedule_file = data.get("file")
                schedule_time = data.get("time")

                # Make sure the schedule is saved as part of the config
                config.load()
                update_or_add_schedule(schedule_file, schedule_time)
                config.save()

                try:
                    job = schedule.every().day.at(data.get("time")).do(lambda: add_file_to_schedule_thread(instance, schedule_file))

                    # Create a unique job ID
                    job_id = str(uuid.uuid4())

                    # Store job reference
                    scheduled_jobs[job_id] = job
                    scheduled_jobs_by_file[schedule_file] = job_id

                    notify_web(instance, "add_schedule", {"added": True, "file": schedule_file, "time": schedule_time, "jobReference": job_id})
                except Exception as e:
                    debug_me(f"Error adding schedule: {e}", "add_tasks_to_scheduler")
                    raise
            # Start the scheduler in a background thread if it's not already started
                start_scheduler()

        except Exception as e:
            if globals.debug:
                debug_me(f"Error in scheduler setup: {e}", "add_tasks_to_scheduler")
                raise
            else:
                pass



    def update_or_add_schedule(file_name, new_time):
        for each_schedule in config.schedules:
            if each_schedule["file"] == file_name:
                # Update existing schedule
                each_schedule["time"] = new_time
                return

        # Add new schedule if not found
        config.schedules.append({"file": file_name, "time": new_time})


    # Temporary storage for chunks
    upload_chunks = {}

    @globals.web_socket.on("upload_artwork_chunk")
    def handle_upload_chunk(data):
        """Handles chunked upload"""
        instance = Instance(data.get("instance_id"), "web")

        file_name = data["fileName"]
        chunk_data = data["chunkData"]
        chunk_index = data["chunkIndex"]
        total_chunks = data["totalChunks"]

        if file_name not in upload_chunks:
            upload_chunks[file_name] = {
                "chunks": [],
                "total_chunks": total_chunks,
                "instance": instance
            }

        # Ensure decoding to bytes
        try:
            decoded_chunk = base64.b64decode(chunk_data)
            upload_chunks[file_name]["chunks"].append(decoded_chunk)
        except Exception as e:
            print(f"Error decoding chunk {chunk_index}: {e}")

        #debug_me(f"Received chunk {chunk_index + 1}/{total_chunks} for {file_name}","handle_upload_chunk")

        notify_web(instance, "progress_bar", {"message": f"{chunk_index + 1} of {total_chunks}", "percent": ((chunk_index + 1) / total_chunks) * 100})

    @globals.web_socket.on("upload_complete")
    def handle_upload_complete(data):

        """
        Finalises the upload once all chunks are received
        """

        file_name = data.get("fileName")
        filters = data.get("filters")
        plex_year = data.get("plex_year")
        plex_title = data.get("plex_title")

        instance = Instance(data.get("instance_id"), "web")

        debug_me(f"Upload complete for {file_name}, processing...","handle_upload_complete")
        notify_web(instance, "progress_bar", {"message": f"Upload complete", "percent": 100})

        instance = Instance(data.get("instance_id"), "web")

        if file_name in upload_chunks and len(upload_chunks[file_name]["chunks"]) == int(upload_chunks[file_name]["total_chunks"]):

            debug_me(f"Upload complete for {file_name}, saving file...","handle_upload_complete")
            save_uploaded_file(instance, file_name, filters, plex_title, plex_year)

            # Cleanup after saving the file
            try:
                del upload_chunks[file_name]
            except KeyError:
                pass
        else:
            debug_me(f'Upload complete event received for {file_name}, but with {len(upload_chunks[file_name]["chunks"])} of {int(upload_chunks[file_name]["total_chunks"])}, some chunks are missing.',"handle_upload_complete")
            try:
                del upload_chunks[file_name]
            except KeyError:
                pass

    def save_uploaded_file(instance: Instance, file_name, filters, plex_title, plex_year):
        """Assembles chunks and saves the file"""

        #print(file_name, filters, type(upload_chunks[file_name]["chunks"][0]))  # Debugging

        temp_zip_path = tempfile.mktemp(suffix=".zip")

        with open(temp_zip_path, "wb") as f:
            for chunk in upload_chunks[file_name]["chunks"]:
                if isinstance(chunk, str):  # Convert strings to bytes if needed
                    chunk = chunk.encode('utf-8')
                f.write(chunk)

        del upload_chunks[file_name]  # Free memory
        debug_me(f"Saved ZIP file: {temp_zip_path}","save_uploaded_file")

        extracted_files = extract_and_list_zip(temp_zip_path)

        #debug_me(str(extracted_files),"save_uploaded_file")

        process_uploaded_artwork(instance, extracted_files, filters, plex_title, plex_year)

        notify_web(instance, "upload_complete", {"files": extracted_files})
        update_status(instance, "Finished processing uploaded file.", color="success")


    def extract_and_list_zip(zip_path):
        """Extracts a ZIP file, flattens directories, and returns a list of valid image files."""
        extract_dir = tempfile.mkdtemp()
        valid_files = []
        zip_source = "theposterdb"

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:

            # Pre-process the file list to try and determine if it's a mediux or tpdb file
            # and ignore things that aren't files we're interested in
            for zip_info in zip_ref.infolist():
                filename = os.path.basename(zip_info.filename)  # Get filename only (ignore paths)

                # Skip directories and unwanted metadata files
                if not filename or filename.startswith('.') or filename.lower() in {"ds_store", "__macosx"}:
                    continue

                if filename == "source.txt":
                    zip_source = "mediux"
                elif filename_pattern.match(filename):
                    extracted_path = os.path.join(extract_dir, filename)

                    with zip_ref.open(zip_info.filename) as source, open(extracted_path, "wb") as target:
                        target.write(source.read())

                    valid_files.append(extracted_path)

        file_list = []
        tv_flag = False

        for file in os.listdir(extract_dir):
            full_path = os.path.join(extract_dir, file)
            md5 = utils.calculate_file_md5(full_path)

            artwork = parse_title(os.path.splitext(file)[0])
            artwork["source"] = zip_source
            artwork["path"] = full_path
            artwork["checksum"] = md5
            artwork["id"] = "Upload"
            if artwork['media'] == "TV Show":
                tv_flag = True

            file_list.append(artwork)

        if tv_flag is True:
            for file in file_list:
                if file['media'] != "TV Show":
                    file['media'] = "TV Show"
                    if not file['season']:
                        file['season'] = "Cover"
                    file['episode'] = None

                # Take into account that MediUX downloads sometimes don't label backdrops as backdrops
                # So let's correct that before backdrops get uploaded as covers by checking whether it's a landscape image
                if file['season'] == "Cover" and check_image_orientation(file["path"]) == "landscape":
                    file['season'] = "Backdrop"

        sorted_data = sorted(file_list, key=sort_key)

        return sorted_data

    # Load the web server
    globals.web_socket.run(web_app, host=DEFAULT_WEB_HOST, port=DEFAULT_WEB_PORT, debug=globals.debug) #, ssl_context=("/path/to/fullchain.pem", "/path/to/privkey.pem")

def check_image_orientation(image_path):
    """Check image orientation using ImageService."""
    return ImageService.check_orientation(image_path)

def sort_key(item):
    """Sort key for artwork items - uses UtilityService."""
    return UtilityService.sort_key(item)

# Autoupdate functions

def get_latest_version():
    """Fetch the latest release version from GitHub."""
    return update_service.get_latest_version() if update_service else None

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
                update_log(instance, "@ *** Scheduled import started ***")
                run_bulk_import_scrape_in_thread(instance, content)
        else:
            update_log(instance, f"Scheduled file does not exist: {filename}")
            return
    except FileNotFoundError:
        update_log(instance, f"@ Scheduled import failed due to missing file ({filename})")
    except Exception as e:
        update_log(instance, f"@ Scheduled import unexpectedly failed ({str(e)})")


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
    # If there are no scheduled jobs already...
    if not scheduler_service.has_schedules():
        for each_schedule in config.schedules:
            schedule_file = each_schedule.get("file")
            schedule_time = each_schedule.get("time")

            # Create the callback for this schedule
            def schedule_callback(filename=schedule_file):
                add_file_to_schedule_thread(instance, filename)

            # Add to scheduler service
            job_id = scheduler_service.add_schedule(
                schedule_file,
                schedule_time,
                schedule_callback
            )

            # Store job reference in config and legacy dicts
            each_schedule["jobReference"] = job_id
            scheduled_jobs_by_file[schedule_file] = job_id

        # Start the scheduler
        if scheduler_service.start():
            debug_me("Scheduler started.", "setup_scheduler_on_first_load")

        debug_me(config.schedules, "setup_scheduler_on_first_load")


# Update the job references for any scheduled jobs if we reload the config file
def update_scheduled_jobs():
    for each_schedule in config.schedules:
        each_schedule["jobReference"] = scheduled_jobs_by_file[each_schedule["file"]]


# * Main Initialization ---
if __name__ == "__main__":

    # Create an instance object including a unique id and "cli" mode to pass around
    cli_instance = Instance(uuid.uuid4(), InstanceMode.CLI.value)

    scheduler_thread = None

    # Updated regex: "Movie Title (YYYY).png" OR "Movie Title.png"
    filename_pattern = re.compile(r'^[^/]+(?:\.jpg|\.jpeg|\.png)$', re.IGNORECASE)

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
                          year=args.year)  # Arguments per url to process

    # Create config as a global object
    config = Config()

    # Load the config from the config.json file
    try:
        config.load()
    except ConfigLoadError:
        sys.exit("Can't load config.json file.  Please check that the file exists and is in the correct format.")
    except Exception as config_load_exception:
        sys.exit(f"Unexpected error when loading config.json file: {str(config_load_exception)}")

    # Create services
    bulk_file_service = BulkFileService(get_exe_dir())
    scheduler_service = SchedulerService(check_interval=SCHEDULER_CHECK_INTERVAL)
    update_service = UpdateService(
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
            parse_bulk_file_from_cli(cli_instance, args.bulk_file if args.bulk_file else config.bulk_txt)

        # Now we're looking at URLs - firstly one containing a TPDb user
        elif "/user/" in cli_command:

            # Remove some of the command line options which aren't applicable to user scraping
            cli_options.year = None
            cli_options.add_posters = False
            cli_options.add_sets = False
            try:
                scrape_tpdb_user(cli_instance, cli_command, cli_options)
            except Exception as e:
                debug_me(f"Error scraping user: {str(e)}","__main__")
                print(f"Error scraping TPDb user: {str(e)}")

        # User passed in a poster or set URL, so let's process that
        else:
            try:
                scrape_and_upload(cli_instance, cli_command, cli_options)
            except Exception as e:
                update_status(cli_instance, str(e),color="danger")
    else:

        # If no CLI arguments, proceed with UI creation (if not in interactive CLI mode)
        if not interactive_cli:

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
            globals.web_socket = SocketIO(web_app, cors_allowed_origins="*", async_mode="eventlet")

            # Start update checker using UpdateService
            def on_update_available(version: str):
                debug_me(f"Later version: {version}", "update_service")
                notify_web(Instance(broadcast=True), "update_available", {"version": version})

            update_service.start_periodic_check(on_update_available)

            setup_web_sockets()

