import base64
from pathlib import Path

import uuid
import os
import re
import zipfile
import tempfile

from PIL import Image
from flask import Flask, render_template
from flask_socketio import SocketIO

import schedule, time

import globals
import threading
import atexit
import sys

import utils
from instance import Instance
from media_metadata import parse_title
from notifications import update_log, update_status, notify_web, debug_me
from config_exceptions import ConfigLoadError
from plex_connector_exception import PlexConnectorException
import arguments
from config import Config
from scraper_exceptions import ScraperException
from theposterdb_scraper import ThePosterDBScraper
from upload_processor import UploadProcessor
from scraper import Scraper
from utils import is_not_comment, parse_url_and_options
from options import Options
from plex_connector import PlexConnector
from upload_processor_exceptions import CollectionNotFound, MovieNotFound, ShowNotFound, NotProcessedByFilter, \
    NotProcessedByExclusion

# ! Interactive CLI mode flag
interactive_cli = False  # Set to False when building the executable with PyInstaller for it launches the web UI by default
mode = "cli"
scheduled_jobs = {}
scheduled_jobs_by_file = {}

# @ ---------------------- CORE FUNCTIONS ----------------------

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
                except:
                    print("Oops")

def cleanup():

    """Function to handle cleanup tasks on exit."""

    debug_me("-----------------------------------------------------------------------------------")

    try:
        if plex:
            debug_me("Closing Plex server connection...")
        debug_me("Exiting application. Cleanup complete.")
    except:
        pass


atexit.register(cleanup)


# @ ---------------------- GUI FUNCTIONS ----------------------

# * UI helper functions ---

def get_exe_dir():
    """Get the directory of the executable or script file."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)  # Path to executable
    else:
        return os.path.dirname(__file__)  # Path to script file


def process_scrape_url_from_ui(instance: Instance, url: str) -> None:

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
        if plex.tv_libraries is None or plex.movie_libraries is None:
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
        if parsed_line.options.add_to_bulk and title:
            notify_web(instance, "add_to_bulk_list", {"url": url, "title": title})

    except ScraperException as scraping_error:
        update_status(instance, f"{scraping_error}", color="danger")

    finally:
        if instance.mode == "web":
            notify_web(instance, "element_disable", {"element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False})


def run_bulk_import_scrape_thread(instance: Instance, web_list = None):

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
        if instance.mode == "web":
            update_status(instance, "No bulk import entries found.", color="danger")

    if instance.mode == "web":
        notify_web(instance, "element_disable", {"element": ["scrape_url", "scrape_button", "bulk_button"], "mode": True})

    # Pass the processing of the parsed URLs off to a thread
    if instance.mode == "web":
        try:
            process_bulk_import_from_ui(instance, parsed_urls)
        except:
            raise


def process_bulk_import_from_ui(instance: Instance, parsed_urls: list) -> None:

    """
    Process the bulk import scrape, based on the contents of the Bulk Import tab in the GUI.

    The bulk import list doesn't need to have been saved, it will use the list as it exists in the GUI currently.

    Args:
        instance:
        parsed_urls:    The URLs to scrape.  These can be theposterdb poster, set or user URL or a mediux set URL.
    """

    global plex

    try:

        # Check if plex setup returned valid values
        if plex.tv_libraries is None or plex.movie_libraries is None:
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

            notify_web(instance, "progress_bar", {"message": f"{i + 1} of {len(parsed_urls)}", "percent" : ((i + 1 / len(parsed_urls)) * 100)})

        # All done, update the UI
        notify_web(instance, "progress_bar", {"message": f"{len(parsed_urls)} of {len(parsed_urls)}", "percent" : 100})
        update_status(instance, "Bulk import scraping completed.", color="success")

    except Exception as e:
        notify_web(instance, "progress_bar", {"percent": 100})
        update_status(instance, f"Error during bulk import: {e}", color="danger")

    finally:
        if instance.mode == "web":
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
        debug_me(str(cannot_scrape))
        raise

    try:
        for page in range(pages):
            page_url = f"{url}?section=uploads&page={page + 1}"
            scrape_and_upload(instance, page_url, options)
    except Exception:
        raise ScraperException(f"Failed to process and upload from URL: {url}")


# Scraped the URL then uploads what it's scraped to Plex
def scrape_and_upload(instance: Instance, url, options):

    global plex

    # Check the connection to Plex
    try:
        plex.connect()
    except PlexConnectorException as not_connected:
        update_status(instance, str(not_connected), "danger")
        raise

    # Let's scrape the posters first
    scraper = Scraper(url)
    scraper.set_options(options)
    try:
        scraper.scrape()
        title = scraper.title
    except ScraperException:
        raise
    except Exception as e:
        raise Exception(e)


    # Now upload them to Plex
    processor = UploadProcessor(plex)
    processor.set_options(options)

    if scraper.collection_artwork:
        for artwork in scraper.collection_artwork:
            try:
                update_status(instance, f'Processing artwork for {artwork["title"]}', spinner=True, sticky=True)
                result = processor.process_collection_artwork(artwork)
                update_log(instance, result)
            except CollectionNotFound as not_found:
                update_log(instance, f"∙ {str(not_found)}")
            except NotProcessedByExclusion as excluded:
                update_log(instance, f"- {str(excluded)}")
            except NotProcessedByFilter as not_processed:
                update_log(instance, f"- {str(not_processed)}")
            except Exception as error_unexpected:
                update_log(instance, f"x {str(error_unexpected)}")
                update_status(instance, f"Error: {str(error_unexpected)}", "danger")

    if scraper.movie_artwork:
        for artwork in scraper.movie_artwork:
            try:
                update_status(instance, f'Processing artwork for {artwork["title"]}', spinner=True, sticky=True)
                result = processor.process_movie_artwork(artwork)
                update_log(instance, result)
            except MovieNotFound as not_found:
                update_log(instance, f"∙ {str(not_found)}")
            except NotProcessedByExclusion as excluded:
                update_log(instance, f"- {str(excluded)}")
            except NotProcessedByFilter as not_processed:
                update_log(instance, f"- {str(not_processed)}")
            except Exception as error_unexpected:
                update_log(instance, f"x {str(error_unexpected)}")
                update_status(instance, f"Error: {str(error_unexpected)}", "danger")



    if scraper.tv_artwork:
        for artwork in scraper.tv_artwork:
            try:
                update_status(instance, f'Processing artwork for {artwork["title"]}', spinner=True, sticky=True)
                result = processor.process_tv_artwork(artwork)
                update_log(instance, result)
            except ShowNotFound as not_found:
                update_log(instance, f"∙ {str(not_found)}")
            except NotProcessedByExclusion as excluded:
                update_log(instance, f"- {str(excluded)}")
            except NotProcessedByFilter as not_processed:
                update_log(instance, f"- {str(not_processed)}")
            except Exception as error_unexpected:
                update_log(instance, f"x {str(error_unexpected)}")
                update_status(instance, f"Error: {str(error_unexpected)}", "danger")

    return title

def process_uploaded_artwork(instance: Instance, file_list):

    global plex

    # Upload the artwork to Plex
    processor = UploadProcessor(plex)
    debug_me("Processing uploaded file and uploading to Plex...")
    for artwork in file_list:
        try:
            result = None
            line_status = f'Processing artwork for {artwork["media"].lower()} "{artwork["title"]}"{" - Season " + str(artwork["season"]) if artwork["season"] else ""}{", Episode " + str(artwork["episode"]) if artwork["episode"] else ""}'
            debug_me(line_status)
            update_status(instance, line_status, spinner=True, sticky=True)
            if artwork['media'] == "Collection":
                result = processor.process_collection_artwork(artwork)
            elif artwork['media'] == "Movie":
                result = processor.process_movie_artwork(artwork)
            elif artwork['media'] == "TV Show":
                result = processor.process_tv_artwork(artwork)
            update_log(instance, result)
        except CollectionNotFound as not_found:
            update_log(instance, f"∙ {str(not_found)}")
        except NotProcessedByExclusion as excluded:
            update_log(instance, f"- {str(excluded)}")
        except NotProcessedByFilter as not_processed:
            update_log(instance, f"- {str(not_processed)}")
        except Exception as error_unexpected:
            update_log(instance, f"x {str(error_unexpected)}")
            update_status(instance, f"Error: {str(error_unexpected)}", "danger")



# * Bulk import file I/O functions ---
def load_bulk_import_file(instance: Instance, filename = None):

    """Load the bulk import file into the text area."""

    global config

    try:
        # Get the current bulk_txt value from the config
        bulk_import_filename = filename if filename is not None else config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt"
        bulk_imports_path = "bulk_imports/"

        # Use get_exe_dir() to determine the correct path for both frozen and non-frozen cases
        bulk_import_file = os.path.join(get_exe_dir(), bulk_imports_path, bulk_import_filename)

        if not os.path.exists(bulk_import_file):
            if instance.mode == "cli":
                print(f"File does not exist: {bulk_import_file}")
            if instance.mode == "web":
                update_status(instance, f"File does not exist: {bulk_import_file}")
            return

        with open(bulk_import_file, "r", encoding="utf-8") as file:
            content = file.read()

        if instance.mode == "web":
            notify_web(instance, "load_bulk_import", {"loaded": True, "filename": bulk_import_filename, "bulk_import_text":content})

    except FileNotFoundError:
        notify_web(instance, "load_bulk_import", {"loaded": False})
    except Exception as e:
        notify_web(instance, "load_bulk_import", {"loaded": False})


def rename_bulk_import_file(instance: Instance, old_name, new_name):

    bulk_imports_path = "bulk_imports/"

    debug_me(f"Renaming file from {old_name} to {new_name}")

    if old_name != new_name:
        try:

            # Use get_exe_dir() to determine the correct path for both frozen and non-frozen cases
            old_filename = os.path.join(get_exe_dir(), bulk_imports_path, old_name)
            new_filename = os.path.join(get_exe_dir(), bulk_imports_path, new_name)
            os.rename(old_filename, new_filename)

            notify_web(instance, "rename_bulk_file", {"renamed": True, "old_filename": old_name, "new_filename": new_name})
            update_status(instance, f"Renamed to {new_name}", "success")
        except Exception as e:
            notify_web(instance, "rename_bulk_file", {"renamed": False, "old_filename": old_name})
            update_status(instance, f"Could not rename {old_name}", "warning")


def delete_bulk_import_file(instance: Instance, file_name):

    bulk_imports_path = "bulk_imports/"

    if file_name:
        try:

            # Use get_exe_dir() to determine the correct path for both frozen and non-frozen cases
            filename = os.path.join(get_exe_dir(), bulk_imports_path, file_name)
            os.remove(filename)

            notify_web(instance, "delete_bulk_file", {"deleted": True, "filename": file_name})
            update_status(instance, f"Deleted {file_name}", "success")
        except Exception as e:
            notify_web(instance, "delete_bulk_file", {"deleted": False, "filename": file_name})
            update_status(instance, f"Could not delete {file_name}", "warning")


def save_bulk_import_file(instance: Instance, contents = None, filename = None, now_load = None):
    """Save the bulk import text area content to a file relative to the executable location."""

    if contents:
        try:
            exe_path = get_exe_dir()
            bulk_import_path = "bulk_imports/"
            bulk_import_file = os.path.join(exe_path, bulk_import_path, filename if filename is not None else config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt")

            os.makedirs(os.path.dirname(bulk_import_file), exist_ok=True)

            debug_me("Saving" + bulk_import_file)

            with open(bulk_import_file, "w", encoding="utf-8") as file:
                file.write(contents)

            debug_me(instance.id)

            update_status(instance, message="Bulk import file " + filename + " saved", color="success")
            notify_web(instance, "save_bulk_import", {"saved": True, "now_load": now_load})
        except Exception as e:
            update_status(instance, message="Error saving bulk import file", color="danger")
            notify_web(instance, "save_bulk_import", {"saved": False, "now_load": now_load})


def check_for_bulk_import_file(instance: Instance):
    """Check if any .txt files exist in the bulk_imports folder before creating bulk_import.txt."""
    contents = "## This is a blank bulk import file\n// You can use comments with # or // like this"

    try:
        exe_path = get_exe_dir()
        bulk_import_path = os.path.join(exe_path, "bulk_imports")
        bulk_import_file = os.path.join(bulk_import_path, config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt")

        # Firstly, make sure the bulk_imports folder exists
        os.makedirs(bulk_import_path, exist_ok=True)

        # And that the default bulk file doesn't exist...
        if not os.path.isfile(bulk_import_file):
            with open(bulk_import_file, "w", encoding="utf-8") as file:
                file.write(contents)

    except Exception as e:
        update_status(instance, message="Error creating bulk import file", color="danger")


def setup_web_sockets():

    @web_app.route("/")
    def home():
        return render_template("web_interface.html", config=config)


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
            process_scrape_url_from_ui(instance, url)

    @globals.web_socket.on("start_bulk_import")
    def handle_bulk_import_from_web(data):
        
        instance = Instance(data.get("instance_id"),"web")
        bulk_list = data.get("bulk_list").lower()
        run_bulk_import_scrape_thread(instance, bulk_list)


    @globals.web_socket.on("save_bulk_import")
    def handle_bulk_import(data):
        instance = Instance(data.get("instance_id"),"web")
        content = data.get("content")
        filename = data.get("filename")
        now_load = data.get("now_load")
        if content:
            debug_me(instance.id)
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
        except:
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
        debug_me(data.get("message"))

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
            plex.reconnect(config)
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
                except:
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
                except:
                    raise
            # Start the scheduler in a background thread if it's not already started
                start_scheduler()

        except:
            if globals.debug:
                raise
            else:
                pass



    def update_or_add_schedule(file_name, new_time):
        for eacH_schedule in config.schedules:
            if eacH_schedule["file"] == file_name:
                # Update existing schedule
                eacH_schedule["time"] = new_time
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
            upload_chunks[file_name] = []

        upload_chunks[file_name].append(base64.b64decode(chunk_data))

        debug_me(f"Received chunk {chunk_index + 1}/{total_chunks} for {file_name}")

        if len(upload_chunks[file_name]) == total_chunks:
            save_uploaded_file(instance, file_name)

    def save_uploaded_file(instance: Instance, file_name):
        """Assembles chunks and saves the file"""
        temp_zip_path = tempfile.mktemp(suffix=".zip")

        with open(temp_zip_path, "wb") as f:
            for chunk in upload_chunks[file_name]:
                f.write(chunk)

        del upload_chunks[file_name]  # Free memory
        debug_me(f"Saved ZIP file: {temp_zip_path}")

        extracted_files = extract_and_list_zip(temp_zip_path)

        debug_me(str(extracted_files))

        process_uploaded_artwork(instance, extracted_files)

        notify_web(instance, "upload_complete", {"files": extracted_files})
        update_status(instance, "Finished processing uploaded file.", color="success")


    # Updated regex: "Movie Title (YYYY).png" OR "Movie Title.png"
    FILENAME_PATTERN = re.compile(r'^[^/]+(?:\.jpg|\.jpeg|\.png)$', re.IGNORECASE)

    def extract_and_list_zip(zip_path):
        """Extracts a ZIP file, flattens directories, and returns a list of valid image files."""
        extract_dir = tempfile.mkdtemp()
        valid_files = []
        zip_source = "theposterdb"

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for zip_info in zip_ref.infolist():
                filename = os.path.basename(zip_info.filename)  # Get filename only (ignore paths)

                # Skip directories and unwanted metadata files
                if not filename or filename.startswith('.') or filename.lower() in {"ds_store", "__macosx"}:
                    continue

                if filename == "source.txt":
                    zip_source = "mediux"
                elif FILENAME_PATTERN.match(filename):
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
    globals.web_socket.run(web_app, host="0.0.0.0", port=4567, debug=globals.debug) #, ssl_context=("/path/to/fullchain.pem", "/path/to/privkey.pem")

def check_image_orientation(image_path):
    with Image.open(image_path) as img:
        width, height = img.size

    if width > height:
        return "landscape"
    elif width < height:
        return "portrait"
    else:
        return "square"

def sort_key(item):
    def parse_season(season):
        # If the season is missing, None, or non-numeric, treat it as the highest possible value
        if season is None or not isinstance(season, (int, str)) or (isinstance(season, str) and not season.isdigit()):
            return float('inf')
        return int(season)

    def parse_episode(episode):
        # Handle missing or non-numeric episodes
        return int(episode) if isinstance(episode, int) else float('inf')

    def parse_source(source):
        # Treat missing source or invalid entries as empty string to ensure they are last
        return source if source else ''

    # Now safely get the values, even if they are missing
    season_value = parse_season(item.get('season'))  # Using .get() to avoid KeyError
    episode_value = parse_episode(item.get('episode'))  # Same for episode
    source_value = parse_source(item.get('source'))  # Same for source

    return item['media'], season_value, episode_value, source_value





def add_file_to_schedule_thread(instance: Instance, filename):
    if instance:
        threading.Thread(target=process_bulk_file_on_schedule, args=(instance, filename,)).start()

def process_bulk_file_on_schedule(instance, filename):
    global config

    try:
        # Get the current bulk_txt value from the config
        bulk_import_filename = filename if filename is not None else config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt"
        bulk_imports_path = "bulk_imports/"

        # Use get_exe_dir() to determine the correct path for both frozen and non-frozen cases
        bulk_import_file = os.path.join(get_exe_dir(), bulk_imports_path, bulk_import_filename)

        if not os.path.exists(bulk_import_file):
            update_log(instance, f"Scheduled file does not exist: {bulk_import_file}")
            return

        with open(bulk_import_file, "r", encoding="utf-8") as file:
            content = file.read()

        if content:
            update_log(instance, "@ *** Scheduled import started ***")
            run_bulk_import_scrape_thread(instance, content)

    except FileNotFoundError:
        update_log(instance, f"@ Scheduled import failed due to missing file ({filename})")
    except Exception as e:
        update_log(instance, f"@ Scheduled import failed ({str(e)})")

# Function to run the scheduler in a separate thread
def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute

# Function to start the scheduler safely
def start_scheduler():
    global scheduler_thread
    if scheduler_thread is None or not scheduler_thread.is_alive():
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        debug_me("Scheduler started.")
    else:
        debug_me("Scheduler is already running.")

def setup_scheduler(instance: Instance):

    if not scheduled_jobs:
        for each_schedule in config.schedules:
            schedule_file = each_schedule.get("file")
            schedule_time = each_schedule.get("time")

            job = schedule.every().day.at(schedule_time).do(lambda: add_file_to_schedule_thread(instance, schedule_file))

            # Create a unique job ID
            job_id = str(uuid.uuid4())

            # Store job reference
            scheduled_jobs[job_id] = job
            scheduled_jobs_by_file[schedule_file] = job_id

            each_schedule["jobReference"] = job_id

        print(config.schedules)

def update_scheduled_jobs():
    for each_schedule in config.schedules:
        each_schedule["jobReference"] = scheduled_jobs_by_file[each_schedule["file"]]

# * Main Initialization ---
if __name__ == "__main__":

    # Regex pattern for movie poster filenames
    FILENAME_PATTERN = re.compile(r'^(.*) \((\d{4})\)\.png$')

    globals.debug = True

    # Create an instance object including a unique id and "cli" mode to pass around
    cli_instance = Instance(uuid.uuid4(),"cli")

    scheduler_thread = None

    # Process command line arguments
    args = arguments.parse_arguments()

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

    # Make sure there's at least one bulk_import file
    check_for_bulk_import_file(cli_instance)

    # Create a connector for Plex
    plex = PlexConnector(config.base_url, config.token)

    # Setup scheduler
    setup_scheduler(cli_instance)

    # Check for CLI arguments regardless of interactive_cli flag
    if cli_command:

        # Connect to the TV and Movie libraries
        try:
            plex.set_tv_libraries(config.tv_library)
        except PlexConnectorException as e:
            sys.exit(str(e))

        try:
            plex.set_movie_libraries(config.movie_library)
        except PlexConnectorException as e:
            sys.exit(str(e))

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
            except:
                debug_me("Oops - handle this user error properly!")

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
            try:
                plex.set_tv_libraries(config.tv_library)
            except PlexConnectorException as e:
                # sys.exit(str(e))
                pass
            try:
                plex.set_movie_libraries(config.movie_library)
            except PlexConnectorException as e:
               # sys.exit(str(e))
                pass

            # Create the app and web server

            web_app = Flask(__name__, template_folder="templates")
            globals.web_socket = SocketIO(web_app, cors_allowed_origins="*")
            setup_web_sockets()

