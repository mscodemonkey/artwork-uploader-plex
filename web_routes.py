"""
Web routes and Socket.IO handlers for the Flask application.

This module contains all Flask routes and Socket.IO event handlers,
extracted from artwork_uploader.py for better organization and maintainability.

The routes are organized into:
- HTTP routes (Flask @app.route)
- Socket.IO event handlers (@socket.on)
- Helper functions for file uploads and processing
"""

import os
import sys
import re
import uuid
import base64
import tempfile
import zipfile
import threading
import subprocess
from pathlib import Path

from flask import render_template, send_from_directory
import schedule

import globals
import utils
from instance import Instance
from config import Config
from media_metadata import parse_title
from notifications import update_log, update_status, notify_web, debug_me
from services import UtilityService


def setup_routes(web_app, config: Config):
    """
    Set up Flask HTTP routes.

    Args:
        web_app: Flask application instance
        config: Configuration object
    """
    @web_app.route("/")
    def home():
        """Render the main web interface."""
        return render_template("web_interface.html", config=config)

    @web_app.route('/downloads/<path:filename>')
    def download_file(filename):
        """Serve files from the downloads directory."""
        downloads_path = os.path.join(UtilityService.get_exe_dir(), 'downloads')
        return send_from_directory(downloads_path, filename, as_attachment=True)

    @web_app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        """Serve files from the uploads directory."""
        uploads_path = os.path.join(UtilityService.get_exe_dir(), 'uploads')
        return send_from_directory(uploads_path, filename)


def setup_socket_handlers(
    config: Config,
    scheduled_jobs: dict,
    scheduled_jobs_by_file: dict,
    filename_pattern: re.Pattern
):
    """
    Set up Socket.IO event handlers.

    Args:
        config: Configuration object
        scheduled_jobs: Dictionary of scheduled jobs by job_id
        scheduled_jobs_by_file: Dictionary mapping filename to job_id
        filename_pattern: Regex pattern for validating filenames

    Note: This function imports from artwork_uploader to avoid circular dependencies.
          It uses globals.web_socket which must be initialized before calling.
    """
    # Import functions from artwork_uploader (to avoid circular imports at module level)
    from artwork_uploader import (
        process_scrape_url_from_web,
        run_bulk_import_scrape_in_thread,
        save_bulk_import_file,
        load_bulk_import_file,
        rename_bulk_import_file,
        delete_bulk_import_file,
        process_uploaded_artwork,
        add_file_to_schedule_thread,
        update_scheduled_jobs,
        get_latest_version,
        current_version,
        check_image_orientation,
        sort_key
    )

    # Temporary storage for chunked uploads
    upload_chunks = {}

    @globals.web_socket.on("check_for_update")
    def check_for_update(data):
        """Check for updates when requested by the frontend."""
        instance = Instance(data.get("instance_id"), "web")
        latest_version = get_latest_version()
        if latest_version and latest_version != current_version:
            notify_web(instance, "update_available", {"version": latest_version})

    @globals.web_socket.on("update_app")
    def update_app(data):
        """Pull updates from GitHub and restart the app."""
        instance = Instance(data.get("instance_id"), "web")

        try:
            update_status(
                Instance(broadcast=True),
                "Updating to the latest version, please wait...",
                "info",
                sticky=True,
                spinner=True
            )

            # Detect platform
            python_cmd = "python3" if sys.platform == "darwin" else "python"

            # Pull latest changes
            subprocess.run(["git", "pull"], check=True)

            # Install dependencies
            subprocess.run([python_cmd, "-m", "pip", "install", "-r", "requirements.txt"], check=True)

            # Trigger the front-end to restart
            update_status(
                Instance(broadcast=True),
                "Update complete, restarting the app...",
                "success",
                sticky=True,
                spinner=True
            )
            notify_web(Instance(broadcast=True), "backend_restarting", {})

            # Restart the app
            os.execlp(python_cmd, python_cmd, "artwork_uploader.py")

        except Exception as e:
            update_status(Instance(broadcast=True), "Update failed, restarting the app...", "danger")
            notify_web(instance, "update_failed", {"error": str(e)})

    @globals.web_socket.on("start_scrape")
    def handle_scrape_from_web(data):
        """Handle scraping request from web UI."""
        instance = Instance(data.get("instance_id"), "web")
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
            notify_web(
                instance,
                "element_disable",
                {"element": ["scrape_url", "scrape_button", "bulk_button"], "mode": True}
            )
            process_scrape_url_from_web(instance, url)

    @globals.web_socket.on("start_bulk_import")
    def handle_bulk_import_from_web(data):
        """Handle bulk import request from web UI."""
        instance = Instance(data.get("instance_id"), "web")
        bulk_list = data.get("bulk_list").lower()
        run_bulk_import_scrape_in_thread(instance, bulk_list)

    @globals.web_socket.on("save_bulk_import")
    def handle_bulk_import(data):
        """Save bulk import file from web UI."""
        instance = Instance(data.get("instance_id"), "web")
        content = data.get("content")
        filename = data.get("filename")
        now_load = data.get("now_load")
        if content:
            save_bulk_import_file(instance, content, filename, now_load)

    @globals.web_socket.on("load_config")
    def load_config_web(data):
        """Load configuration from web UI."""
        instance = Instance(data.get("instance_id"), "web")
        config.load()
        update_scheduled_jobs()
        notify_web(instance, "load_config", {"config": vars(config)})

    @globals.web_socket.on("load_bulk_filelist")
    def load_bulk_filelist(data):
        """Load list of bulk import files."""
        instance = Instance(data.get("instance_id"), "web")
        bulk_files = None
        try:
            folder_path = Path("bulk_imports")
            bulk_files = [f.name for f in folder_path.iterdir() if f.is_file()]
        except (FileNotFoundError, PermissionError) as e:
            debug_me(f"Error loading bulk file list: {e}", "load_bulk_filelist")
        notify_web(instance, "load_bulk_filelist", {"bulk_files": bulk_files})

    @globals.web_socket.on("load_bulk_import")
    def load_bulk_import(data):
        """Load a specific bulk import file."""
        instance = Instance(data.get("instance_id"), "web")
        load_bulk_import_file(instance, data.get("filename"))

    @globals.web_socket.on("rename_bulk_file")
    def rename_bulk_file(data):
        """Rename a bulk import file."""
        instance = Instance(data.get("instance_id"), "web")
        rename_bulk_import_file(instance, data.get("old_filename"), data.get("new_filename"))

    @globals.web_socket.on("delete_bulk_file")
    def delete_bulk_file(data):
        """Delete a bulk import file."""
        instance = Instance(data.get("instance_id"), "web")
        delete_bulk_import_file(instance, data.get("filename"))

    @globals.web_socket.on("display_message")
    def display_message(data):
        """Log a debug message from the frontend."""
        debug_me(data.get("message"), "display_message")

    @globals.web_socket.on("save_config")
    def save_config_web(data):
        """Save configuration from web UI."""
        instance = Instance(data.get("instance_id"), "web")

        try:
            # Unpack the config dictionary into the local config
            for key, value in data.get("config").items():
                setattr(config, key, value)
            config.save()

            # Reconnect to Plex because the Plex server or token might have changed
            update_log(instance, "Saving updated configuration and reconnecting to Plex")
            globals.plex.reconnect(config)
            notify_web(instance, "save_config", {"saved": True, "config": vars(config)})
        except Exception as config_error:
            update_status(instance, str(config_error), color="danger")

    @globals.web_socket.on("delete_schedule")
    def delete_task_from_scheduler(data):
        """Delete a scheduled task."""
        if data.get("instance_id"):
            instance = Instance(data.get("instance_id"), "web")
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
                    config.schedules = [
                        each_schedule
                        for each_schedule in config.schedules
                        if each_schedule["file"] != schedule_file
                    ]
                    config.save()

                    # And update the front-end
                    notify_web(
                        instance,
                        "delete_schedule",
                        {"file": schedule_file, "job_reference": job_id, "deleted": True}
                    )
                else:
                    notify_web(instance, "delete_schedule", {"deleted": False, "job_id": job_id})

    @globals.web_socket.on("add_schedule")
    def add_tasks_to_scheduler(data):
        """Add a new scheduled task."""
        try:
            # Schedule bulk import task
            if data.get("instance_id"):
                instance = Instance(data.get("instance_id"), "web")
                schedule_file = data.get("file")
                schedule_time = data.get("time")

                # Make sure the schedule is saved as part of the config
                config.load()
                update_or_add_schedule(schedule_file, schedule_time)
                config.save()

                try:
                    job = schedule.every().day.at(data.get("time")).do(
                        lambda: add_file_to_schedule_thread(instance, schedule_file)
                    )

                    # Create a unique job ID
                    job_id = str(uuid.uuid4())

                    # Store job reference
                    scheduled_jobs[job_id] = job
                    scheduled_jobs_by_file[schedule_file] = job_id

                    notify_web(
                        instance,
                        "add_schedule",
                        {
                            "added": True,
                            "file": schedule_file,
                            "time": schedule_time,
                            "jobReference": job_id
                        }
                    )
                except Exception as e:
                    debug_me(f"Error adding schedule: {e}", "add_tasks_to_scheduler")
                    raise

                # Start the scheduler in a background thread if it's not already started
                from artwork_uploader import start_scheduler
                start_scheduler()

        except Exception as e:
            if globals.debug:
                debug_me(f"Error in scheduler setup: {e}", "add_tasks_to_scheduler")
                raise

    def update_or_add_schedule(file_name, new_time):
        """Helper function to update or add a schedule in config."""
        for each_schedule in config.schedules:
            if each_schedule["file"] == file_name:
                # Update existing schedule
                each_schedule["time"] = new_time
                return

        # Add new schedule if not found
        config.schedules.append({"file": file_name, "time": new_time})

    @globals.web_socket.on("upload_artwork_chunk")
    def handle_upload_chunk(data):
        """Handle chunked file upload."""
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

        notify_web(
            instance,
            "progress_bar",
            {
                "message": f"{chunk_index + 1} of {total_chunks}",
                "percent": ((chunk_index + 1) / total_chunks) * 100
            }
        )

    @globals.web_socket.on("upload_complete")
    def handle_upload_complete(data):
        """Finalize the upload once all chunks are received."""
        file_name = data.get("fileName")
        filters = data.get("filters")
        plex_year = data.get("plex_year")
        plex_title = data.get("plex_title")

        instance = Instance(data.get("instance_id"), "web")

        debug_me(f"Upload complete for {file_name}, processing...", "handle_upload_complete")
        notify_web(instance, "progress_bar", {"message": "Upload complete", "percent": 100})

        if file_name in upload_chunks and len(upload_chunks[file_name]["chunks"]) == int(
            upload_chunks[file_name]["total_chunks"]
        ):
            debug_me(f"Upload complete for {file_name}, saving file...", "handle_upload_complete")
            save_uploaded_file(
                instance,
                file_name,
                filters,
                plex_title,
                plex_year,
                upload_chunks,
                filename_pattern,
                check_image_orientation,
                sort_key
            )

            # Cleanup after saving the file
            try:
                del upload_chunks[file_name]
            except KeyError:
                pass
        else:
            debug_me(
                f'Upload complete event received for {file_name}, but with '
                f'{len(upload_chunks[file_name]["chunks"])} of '
                f'{int(upload_chunks[file_name]["total_chunks"])}, some chunks are missing.',
                "handle_upload_complete"
            )
            try:
                del upload_chunks[file_name]
            except KeyError:
                pass


def save_uploaded_file(
    instance: Instance,
    file_name: str,
    filters: list,
    plex_title: str,
    plex_year: int,
    upload_chunks: dict,
    filename_pattern: re.Pattern,
    check_image_orientation_func,
    sort_key_func
):
    """
    Assemble chunks and save the uploaded file.

    Args:
        instance: Instance object for web notifications
        file_name: Name of the uploaded file
        filters: List of filters to apply
        plex_title: Optional title override
        plex_year: Optional year override
        upload_chunks: Dictionary of upload chunks
        filename_pattern: Regex pattern for validating filenames
        check_image_orientation_func: Function to check image orientation
        sort_key_func: Function to generate sort keys
    """
    from artwork_uploader import process_uploaded_artwork

    temp_zip_path = tempfile.mktemp(suffix=".zip")

    with open(temp_zip_path, "wb") as f:
        for chunk in upload_chunks[file_name]["chunks"]:
            if isinstance(chunk, str):  # Convert strings to bytes if needed
                chunk = chunk.encode('utf-8')
            f.write(chunk)

    del upload_chunks[file_name]  # Free memory
    debug_me(f"Saved ZIP file: {temp_zip_path}", "save_uploaded_file")

    extracted_files = extract_and_list_zip(
        temp_zip_path,
        filename_pattern,
        check_image_orientation_func,
        sort_key_func
    )

    process_uploaded_artwork(instance, extracted_files, filters, plex_title, plex_year)

    notify_web(instance, "upload_complete", {"files": extracted_files})
    update_status(instance, "Finished processing uploaded file.", color="success")


def extract_and_list_zip(
    zip_path: str,
    filename_pattern: re.Pattern,
    check_image_orientation_func,
    sort_key_func
) -> list:
    """
    Extract a ZIP file, flatten directories, and return a list of valid image files.

    Args:
        zip_path: Path to the ZIP file
        filename_pattern: Regex pattern for validating filenames
        check_image_orientation_func: Function to check image orientation
        sort_key_func: Function to generate sort keys

    Returns:
        List of artwork dictionaries sorted by media type, season, episode
    """
    extract_dir = tempfile.mkdtemp()
    valid_files = []
    zip_source = "theposterdb"

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # Pre-process the file list to determine source and extract valid files
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

    if tv_flag:
        for file in file_list:
            if file['media'] != "TV Show":
                file['media'] = "TV Show"
                if not file['season']:
                    file['season'] = "Cover"
                file['episode'] = None

            # Take into account that MediUX downloads sometimes don't label backdrops as backdrops
            # So let's correct that before backdrops get uploaded as covers by checking whether it's a landscape image
            if file['season'] == "Cover" and check_image_orientation_func(file["path"]) == "landscape":
                file['season'] = "Backdrop"

    sorted_data = sorted(file_list, key=sort_key_func)

    return sorted_data


def start_web_server(web_app, web_host: str, web_port: int, debug: bool = False):
    """
    Start the Flask web server.

    Args:
        web_app: Flask application instance
        web_host: Host to bind to
        web_port: Port to bind to
        debug: Whether to run in debug mode
    """
    globals.web_socket.run(web_app, host=web_host, port=web_port, debug=debug)
