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
import logging
import flask.cli
import sys
import re
import base64
import tempfile
import zipfile
import subprocess

from pathlib import Path
from packaging import version
from plexapi.server import PlexServer

from flask import render_template, send_from_directory, request, redirect, url_for, session
from functools import wraps

from core import globals
from services.notify_service import NotifyService
from utils import utils
from models.instance import Instance
from core.config import Config
from core.enums import FileType, MediaType, ScraperSource, StatusColor
from processors.media_metadata import parse_title
from utils.notifications import update_log, update_status, notify_web, debug_me
from services import UtilityService, AuthenticationService


def login_required(f):
    """Decorator to require authentication for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get config from globals
        config = globals.config if hasattr(globals, 'config') and globals.config else None

        # If auth not enabled, allow access
        if not config or not config.auth_enabled:
            return f(*args, **kwargs)

        # Check if user is logged in
        if not session.get('authenticated'):
            return redirect(url_for('login'))

        return f(*args, **kwargs)
    return decorated_function


def setup_routes(web_app, config: Config):
    """
    Set up Flask HTTP routes.

    Args:
        web_app: Flask application instance
        config: Configuration object
    """
    @web_app.route("/login", methods=["GET", "POST"])
    def login():
        """Handle user login."""
        # If auth not enabled, redirect to home
        if not config.auth_enabled:
            return redirect(url_for('home'))

        # Already logged in
        if session.get('authenticated'):
            return redirect(url_for('home'))

        error = None

        if request.method == "POST":
            username = request.form.get('username', '')
            password = request.form.get('password', '')
            remember = request.form.get('remember') == 'on'

            # Authenticate
            if AuthenticationService.authenticate(username, password, config.auth_username, config.auth_password_hash):
                session['authenticated'] = True
                session.permanent = remember  # Set to 7 days if remember is checked
                update_log(Instance(broadcast=True), f"👤 User {username} logged in successfully")
                return redirect(url_for('home'))
            else:
                error = "Invalid username or password"
                update_log(Instance(broadcast=True), f"⛔ Invalid username or password provided")

        return render_template("login.html", error=error)

    @web_app.route("/logout")
    def logout():
        """Handle user logout."""
        update_log(Instance(broadcast=True), f"👋🏻 Logout successful")
        session.clear()
        return redirect(url_for('login'))

    @web_app.route("/")
    @login_required
    def home():
        """Render the main web interface."""
        return render_template("web_interface.html", config=config)

    @web_app.route('/downloads/<path:filename>')
    @login_required
    def download_file(filename):
        """Serve files from the downloads directory."""
        downloads_path = os.path.join(UtilityService.get_exe_dir(), 'downloads')
        return send_from_directory(downloads_path, filename, as_attachment=True)

    @web_app.route('/uploads/<path:filename>')
    @login_required
    def uploaded_file(filename):
        """Serve files from the uploads directory."""
        uploads_path = os.path.join(UtilityService.get_exe_dir(), 'uploads')
        return send_from_directory(uploads_path, filename)


def setup_socket_handlers(
    config: Config,
    filename_pattern: re.Pattern
):
    """
    Set up Socket.IO event handlers.

    Args:
        config: Configuration object
        filename_pattern: Regex pattern for validating filenames

    Note: This function imports from artwork_uploader to avoid circular dependencies.
          It uses globals.web_socket which must be initialized before calling.
          Scheduled jobs are now managed through globals.scheduler_service.
    """
    # Import functions from artwork_uploader (to avoid circular imports at module level)
    from artwork_uploader import (
        process_scrape_url_from_web,
        request_scrape_stop,
        run_bulk_import_scrape_in_thread,
        save_bulk_import_file,
        load_bulk_import_file,
        rename_bulk_import_file,
        delete_bulk_import_file,
        add_file_to_schedule_thread,
        update_scheduled_jobs,
        get_latest_version,
        current_version,
        check_image_orientation,
        sort_key
    )

    # Temporary storage for chunked uploads
    upload_chunks = {}

    @globals.web_socket.on("debug_mode")
    def debug_mode(data):
        """Report on debug mode status and toggle debug mode."""
        instance = Instance(data.get("instance_id"), "web")
        if data.get("action") == "get":
            update_log(instance, f"🐞 Debug mode is {'On' if globals.debug else 'Off'}")
            debug_me(f"Reporting current debug mode: {'On' if globals.debug else 'Off'}")
            notify_web(instance, "debug_mode", { "debug": globals.debug })
        elif data.get("action") == "toggle":
            update_log(instance, f"🐞 Debug mode is {'Off' if globals.debug else 'On'}")
            debug_me(f"Turning debug mode {'Off' if globals.debug else 'On'}")
            notify_web(instance, "debug_mode", { "debug": not globals.debug })
            if globals.debug:
                globals.debug = False
            else:
                globals.debug = True

    @globals.web_socket.on("check_for_update")
    def check_for_update(data):
        """Check for updates when requested by the frontend."""
        instance = Instance(data.get("instance_id"), "web", broadcast=True)
        debug_me(f"Checking for update by request from the frontend")
        latest_version = get_latest_version()
        if latest_version and version.parse(latest_version.lstrip('v')) > version.parse(current_version.lstrip('v')):
            update_log(instance, f"🚨 Update available: {latest_version} (current: {current_version})")
            notify_web(instance, "version_check", { "new_version": latest_version, "current_version": current_version, "docker": "true" if globals.docker else "false" })
        else:
            update_log(instance, f"🏷️ You are running the latest version: {current_version}")
            notify_web(instance, "version_check", { "new_version": None, "current_version": current_version, "docker": "true" if globals.docker else "false" })

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
            update_log(instance, "🔄 Starting update process...")

            # Use the exact same python that is currently running this code:
            python_cmd = sys.executable

            # Fetch the latest metadata
            subprocess.run(["git", "fetch", "--all"], check=True)

            # Force move the HEAD to the latest commit on origin/main
            subprocess.run(["git", "reset", "--hard", "origin/main"], check=True)

            # Re-attach to the local 'main' branch and update its pointer
            # This is the step that fixes the "HEAD detached" status
            subprocess.run(["git", "checkout", "-B", "main", "origin/main"], check=True)

            # Clean up any leftover files
            subprocess.run(["git", "clean", "-fd"], check=True)

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
            update_log(instance, f"❌ Update failed: {str(e)}")
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
            process_scrape_url_from_web(instance, url)

    @globals.web_socket.on("stop_scrape")
    def handle_stop_scrape(data):
        """Flag any in-flight scrape to stop cleanly (user pressed Stop in the web UI)."""
        instance = Instance(data.get("instance_id"), "web")
        if not request_scrape_stop():
            update_log(instance, "ℹ️ Nothing to stop - no scrape is running")

    @globals.web_socket.on("start_bulk_import")
    def handle_bulk_import_from_web(data):
        """Handle bulk import request from web UI."""
        instance = Instance(data.get("instance_id"), "web")
        bulk_list = data.get("bulk_list").lower()
        filename = data.get("filename", "bulk_import.txt")
        run_bulk_import_scrape_in_thread(instance, bulk_list, filename)

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
        update_log(instance, "🔄 Configuration loaded")
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
            debug_me(f"Error loading bulk import file list: {e}")
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
        old_name = data.get("old_filename")
        new_name = data.get("new_filename")
        time = globals.scheduler_service.run_times_by_file.get(old_name)
        rename_bulk_import_file(instance, old_name, new_name)
        if time:
            delete_task_from_scheduler({"instance_id": instance.id, "file": old_name})
            add_tasks_to_scheduler({"instance_id": instance.id, "file": new_name, "time": time})

    @globals.web_socket.on("delete_bulk_file")
    def delete_bulk_file(data):
        """Delete a bulk import file."""
        instance = Instance(data.get("instance_id"), "web")
        delete_bulk_import_file(instance, data.get("filename"))

    @globals.web_socket.on("create_bulk_file")
    def create_bulk_file(data):
        """Create a new bulk import file."""
        instance = Instance(data.get("instance_id"), "web")

        from datetime import datetime
        timestamp = datetime.now().strftime("%d %b %Y %H:%M:%S")

        # Generate a unique filename
        base_name = "bulk_import_new"
        extension = ".txt"
        counter = 1
        filename = f"{base_name}{extension}"

        # Check if file exists and increment counter
        while globals.bulk_file_service.file_exists(filename):
            filename = f"{base_name}_{counter}{extension}"
            counter += 1

        # Create file with comment header
        content = f"# Bulk import file created {timestamp}\n"

        try:
            globals.bulk_file_service.write_file(content, filename)
            update_log(instance, f"📝 Created new bulk import file: {filename}")
            notify_web(instance, "create_bulk_file", {"created": True, "filename": filename})
            # Reload the file list
            folder_path = Path("bulk_imports")
            bulk_files = [f.name for f in folder_path.iterdir() if f.is_file()]
            notify_web(instance, "load_bulk_filelist", {"bulk_files": bulk_files})
        except Exception as e:
            update_log(instance, f"🔴 Failed to create new bulk import file")
            update_status(instance, f"Error creating file: {str(e)}", "danger")
            notify_web(instance, "create_bulk_file", {"created": False, "error": str(e)})

    @globals.web_socket.on("display_message")
    def display_message(data):
        """Log a debug message from the frontend."""
        instance = Instance(data.get("instance_id"), "web")
        debug_me(f"Received message from fronted: '{data.get('message')}' • Log level: '{data.get('level')}'")
        if data.get("level") == "debug":
            debug_me(data.get("message"), data.get("title", "web_message"))
        elif data.get("level") == "log":
            update_log(instance, data.get("message"))

    @globals.web_socket.on("test_plex_connect")
    def test_plex_connect(data):
        """Test connectivity to Plex server"""

        def fail(status, log):
            if saving_config:
                log = f"Configuration not saved ({log})"
                status = f"Configuration not saved ({status})"
            update_log(instance, log)
            update_status(instance, status, "danger", False, False, "x-circle")
            notify_web(instance, "test_plex_connect", { "success": False })
            notify_web(instance, "element_disable", { "element": ["test_plex_btn"], "mode": False })

        instance = Instance(data.get("instance_id"), "web")
        instance.broadcast = True
        update_status(instance, "Testing connection to Plex server", "info", True, True)

        # Disable the test button to prevent multiple clicks
        notify_web(instance, "element_disable", {"element": ["test_plex_btn"], "mode": True})
        
        # Capture Plex settings form parameters
        url = data.get("url", "")
        debug_me(f"Obtained Plex URL: {url}")
        token = data.get("token", "")
        debug_me(f"Obtained Plex token: {token}")
        tv_libs = data.get("tv_libs", "")
        debug_me(f"Obtained {len(tv_libs)} TV libraries: {tv_libs}")
        movie_libs = data.get("movie_libs", "")
        debug_me(f"Obtained {len(movie_libs)} Movie libraries: {movie_libs}")
        saving_config = data.get("saving_config")
        if saving_config:
            debug_me(f"Testing Plex connectivity before saving configuration")
        else:
            debug_me(f"Testing Plex connectivity")
        
        # Check for a valid Plex server URL and token
        url_pattern = r"^https?:\/\/([a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)*|(\d{1,3}(\.\d{1,3}){3}))(:\d+)?(\/.*)?$"
        token_pattern = r"^[A-Za-z0-9_-]{20,}$"
        if not re.fullmatch(url_pattern, url):
            fail("Invalid Plex URL", f"❌ Invalid Plex URL")
            return
        if not re.fullmatch(token_pattern, token):
            fail("Invalid Plex token", f"❌ Invalid Plex token")
            return
        
        # Check connectivity to server
        try:
            plex_server = PlexServer(url, token, timeout=5)
        except Exception as e:
            if "NewConnectionError" in str(e):
                log = f"❌ Error connecting to Plex (Connection refused)"
            elif "ConnectTimeoutError" in str(e) or "timed out" in str(e):
                log = f"❌ Error connecting to Plex (Timed out)"
            elif "unauthorized" in str(e):
                log = f"❌ Error connecting to Plex (Invalid token)"
            elif "NameResolutionError" in str(e):
                log = f"❌ Error connecting to Plex (Cannot resolve server name)"
            elif "SSLError" in str(e):
                log = f"❌ Error connecting to Plex (SSL certificate validation failed)"
            else:
                log = f"❌ Unknown error connecting to Plex: {str(e)}"
            fail ("Error connecting to Plex, check log for details", log)
            debug_me(f"Error connecting to Plex: {str(e)}")
            return

        # Check that the provided libraries exist in the server        
        all_libs = list(tv_libs) + list(movie_libs)
        invalid_libs = []
        for lib in all_libs:
            try:
                plex_server.library.section(lib)
            except Exception:
                invalid_libs.append(lib)
        if invalid_libs:
            fail("Some libraries not found, check log for details.", f"❌ The following libraries could not be found: {", ".join (invalid_libs)}")
            return
        
        update_log(instance, "✅ Successfully connected to Plex server")
        update_status(instance, "Successfully connected to Plex server", "success", False, False, "check2-circle")
        notify_web(instance, "element_disable", { "element": ["test_plex_btn"], "mode": False })
        notify_web(instance, "test_plex_connect", { "success": True })

    @globals.web_socket.on("test_notifications")
    def test_notifications(data):
        """Send a test notification."""
        instance = Instance(data.get("instance_id"), "web")
        instance.broadcast = True
        # Disable the test button to prevent multiple clicks
        notify_web(instance, "element_disable", {"element": ["test_notif_btn"], "mode": True})
        urls = data.get("urls", [])
        notification_title = "Test Notification from Artwork Uploader"
        notification_message = "This is a test notification to verify your notification settings are working correctly."
        test_notification = NotifyService()
        success = True
        failed = 0
        for url in urls:
            test_notification.add_url(url)
            debug_me(f"Sending test notification to '{url}'")
            url_success = test_notification.send_notification(notification_title, notification_message)
            success = success and url_success
            if url_success:
                debug_me(f"📢 Test notification sent successfully to '{url}'")
                update_log(instance, f"📢 Test notification sent successfully to '{url}'")
                if len(urls) == 1:
                    update_status(instance, f"Test notification sent successfully", "success", False, False, "check2-circle")
            else:
                failed += 1
                debug_me(f"❌ Test notification failed to send to '{url}'.")
                update_log(instance, f"❌ Test notification failed to send to '{url}'")
                if len(urls) == 1:
                    update_status(instance, f"Test notification failed to send", "danger", False, False, "x-circle")
            test_notification.clear_urls()
        if len(urls) > 1:
            if success and len(urls) > 1:
                debug_me("All test notifications sent successfully")
                update_log(instance, "✅ All test notifications sent successfully")
                update_status(instance, "All test notifications sent successfully", "success", False, False, "check2-circle")
            elif failed < len(urls):
                debug_me("Some test notifications failed to send")
                update_log(instance, "⚠️ Some test notifications failed to send")
                update_status(instance, "Some test notifications failed to send. Check logs for details.", "warning", False, False, "exclamation-triangle")
            else:
                debug_me("All test notifications failed to send")
                update_log(instance, "❌ All test notifications failed to send")
                update_status(instance, "All test notifications failed to send", "danger", False, False, "x-circle")
        notify_web(instance, "element_disable", { "element": ["test_notif_btn"], "mode": False })

    @globals.web_socket.on("save_config")
    def save_config_web(data):
        """Save configuration from web UI."""
        instance = Instance(data.get("instance_id"), "web")

        try:
            # Create new config object and load existing config from config.json
            new_config = Config()
            new_config.load()
            new_config_dict = vars(new_config)
            current_config_dict = vars(globals.config).copy()
            password_change = False
            # Capture the provided password and see if it's different 
            password = data.get("config").get("auth_password")
            if password:
                password_change = not AuthenticationService.verify_password(password, globals.config.auth_password_hash)

            # Unpack the config dictionary into the local config
            for key, value in data.get("config").items():
                new_config_dict[key] = value

            # Prepare configurations to be compared
            new_config_dict.pop("auth_password")
            new_config_dict.pop("auth_password_hash")
            current_config_dict.pop("auth_password_hash")

            # If the new configuration is the same, return
            if new_config_dict == current_config_dict and not password_change:
                update_status(instance, "No configuration change detected", "info", False, False, "info-circle")
                return
            
            if new_config_dict["auth_enabled"] and password:
                if new_config_dict["auth_username"] == current_config_dict["auth_username"] and password_change:
                    update_log(instance, f"🔐 Password changed for user {new_config_dict["auth_username"]}")
                elif new_config_dict["auth_username"] != current_config_dict["auth_username"]:
                    update_log(instance, f"🔐 Authentication enabled for user {new_config_dict["auth_username"]}")
                password_hash = AuthenticationService.hash_password(password)
                new_config_dict["auth_password_hash"] = password_hash

            if not new_config_dict["auth_enabled"]:
                if current_config_dict["auth_enabled"]:
                    update_log(instance, f"🔓 Authentication disabled for user {globals.config.auth_username}")
                new_config_dict["auth_username"] = ""
                new_config_dict["auth_password_hash"] = ""

            # Populate the attributes of the config object with the values provided through the frontend
            for key, value in new_config_dict.items():
                setattr(config, key, value)
            config.save()

            # Also update globals
            globals.config = config

            # Reconnect to Plex because the Plex server or token might have changed
            update_log(instance, "💾 Configuration saved")
            globals.plex.reconnect(config)
            notify_web(instance, "save_config", {"saved": True, "config": vars(config)})
        except Exception as config_error:
            update_status(instance, str(config_error), color=StatusColor.WARNING.value)

    @globals.web_socket.on("delete_schedule")
    def delete_task_from_scheduler(data):
        """Delete a scheduled task."""
        if data.get("instance_id"):
            instance = Instance(data.get("instance_id"), "web")
            schedule_file = data.get("file")

            if schedule_file:
                # Get job ID from scheduler service
                job_id = globals.scheduler_service.get_job_id_by_file(schedule_file)

                if job_id:
                    # Remove from scheduler service
                    globals.scheduler_service.remove_schedule(job_id)

                    # Make sure it's also removed from the config file
                    config.load()
                    config.schedules = [
                        each_schedule
                        for each_schedule in config.schedules
                        if each_schedule["file"] != schedule_file
                    ]
                    config.save()

                    # And update the front-end
                    notify_web(instance, "delete_schedule", { "file": schedule_file, "job_reference": job_id, "deleted": True })
                    update_log(instance, f"🗑️ Deleted scheduled task for '{schedule_file}'")
                    debug_me(f"Deleted scheduled task for '{schedule_file}' with job ID '{job_id}'")
                else:
                    debug_me(f"Couldn't find a scheduled job for '{schedule_file}'")
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
                    # Create the callback for this schedule
                    def schedule_callback(filename=schedule_file):
                        add_file_to_schedule_thread(instance, filename)

                    # Add to scheduler service
                    job_id = globals.scheduler_service.add_schedule(
                        schedule_file,
                        schedule_time,
                        schedule_callback
                    )

                    notify_web(instance, "add_schedule", { "added": True, "file": schedule_file, "time": schedule_time, "jobReference": job_id })
                    update_log(instance, f"⏰ Added scheduled task '{schedule_file}' every day at {schedule_time}")
                    debug_me(f"Added scheduled task '{schedule_file}' every day at {schedule_time} with job ID '{job_id}'")
                except Exception as e:
                    update_log(instance, f"🔴 Failed to add scheduled task '{schedule_file}'")
                    debug_me(f"Error adding schedule: {e}")
                    raise

                # Start the scheduler if it's not already started
                globals.scheduler_service.start()

        except Exception as e:
            debug_me(f"Error in scheduler setup: {e}")
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

    @globals.web_socket.on("detect_docker")
    def docker_detection(data):
        """Detects whether app is running in docker and informs frontend"""
        instance = Instance(data.get("instance_id"), "web")
        if globals.docker:
            kometa_base = utils.get_host_path("/assets")
            temp_dir = utils.get_host_path("/temp")
            update_log(instance, f"🐳 Docker environment detected")
            debug_me(f"Docker detected, Kometa asset path mapped to '{kometa_base}', temp dir mapped to '{temp_dir}'")
            if kometa_base == "(not defined)":
                update_log(instance, "⚠️ Kometa base path is not defined in docker-compose.yml file. Saving assets to Kometa asset directory is not available.")
            notify_web(instance, "docker_detected", { "docker": "true", "kometa_base": kometa_base, "temp_dir": temp_dir })
        else:
            notify_web(instance, "docker_detected", { "docker": "false" })

    @globals.web_socket.on("upload_artwork_chunk")
    def handle_upload_chunk(data):
        """Handle chunked file upload - writes directly to temp file for memory efficiency."""
        
        instance = Instance(data.get("instance_id"), "web")
        file_name = data["fileName"]
        chunk_data = data["chunkData"]
        chunk_index = data["chunkIndex"]
        total_chunks = data["totalChunks"]

        if chunk_index == 0:
            globals.cancel_scrape = False
            globals.scrapes_running += 1
            notify_web(instance, "scrape_state", { "running": True, "type": "upload" })
            notify_web(instance, "element_disable", { "element": ["scrape_url", "scrape_button", "bulk_button"], "mode": True })

        if globals.cancel_scrape:
            debug_me(f"File upload canceled by user")
            update_log(instance, f"🛑 {file_name} • File upload canceled by user")
            update_status(instance, f"File upload canceled by user", color=StatusColor.WARNING.value)
            if file_name in upload_chunks:
                try:
                    upload_chunks[file_name]["temp_file"].close()
                    if os.path.exists(upload_chunks[file_name]["temp_path"]):
                        os.remove(upload_chunks[file_name]["temp_path"])
                except Exception:
                    pass
                del upload_chunks[file_name]            
            globals.scrapes_running -= 1
            if globals.scrapes_running <= 0:
                globals.scrapes_running = 0
                globals.cancel_scrape = False
                notify_web(instance, "scrape_state", { "running": False, "type": "upload" })
                notify_web(instance, "element_disable", { "element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False })
            return "abort"

        if file_name not in upload_chunks:
            # Create a temporary file to stream chunks to disk instead of memory
            temp_file = tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.upload')            
            upload_chunks[file_name] = {
                "temp_file": temp_file,
                "temp_path": temp_file.name,
                "chunks_received": 0,
                "total_chunks": total_chunks,
                "instance": instance
            }

        # Decode and write chunks directly to disk
        try:
            decoded_chunk = base64.b64decode(chunk_data)
            upload_chunks[file_name]["temp_file"].write(decoded_chunk)
            upload_chunks[file_name]["chunks_received"] += 1
            return "ok"
        except Exception as e:
            debug_me(f"Error decoding chunk {chunk_index + 1}: {str(e)}")
            globals.scrapes_running -= 1
            if globals.scrapes_running <= 0:
                globals.scrapes_running = 0
                globals.cancel_scrape = False
                notify_web(instance, "scrape_state", { "running": False, "type": "upload" })
                notify_web(instance, "element_disable", { "element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False })
            return "error"

    @globals.web_socket.on("upload_complete")
    def handle_upload_complete(data):
        """Finalize the upload once all chunks are received."""
        file_name = data.get("fileName")
        filters = data.get("filters")
        plex_year = data.get("plex_year")
        plex_title = data.get("plex_title")
        options = data.get("options")
        debug_me(f"Obtained filters from web form: {filters}")
        debug_me(f"Obtained options from web form: {options}")

        instance = Instance(data.get("instance_id"), "web")

        if file_name in upload_chunks and upload_chunks[file_name]["chunks_received"] == int(
            upload_chunks[file_name]["total_chunks"]
        ):
            temp_path = upload_chunks[file_name]["temp_path"]
            debug_me(f"Uploaded {file_name} to {temp_path}, processing file...")
            upload_chunks[file_name]["temp_file"].close()
            update_log(instance, f"✔️ {file_name} • Upload completed successfully")
            save_uploaded_file(
                instance,
                file_name,
                options,
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
                temp_path = upload_chunks[file_name]["temp_path"]
                # Delete the temp file if it still exists
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                # Delete the metadata for the file
                del upload_chunks[file_name]
            except OSError as e:
                debug_me(f"Error during cleanup: {str(e)}")
        else:
            chunks_received = upload_chunks[file_name]["chunks_received"] if file_name in upload_chunks else 0
            expected_chunks = upload_chunks[file_name]["total_chunks"] if file_name in upload_chunks else 0
            debug_me(
                f'Upload complete event received for {file_name}, but with '
                f'{chunks_received} of {expected_chunks}, some chunks are missing.'
            )
            try:
                # Clean up temp file
                if file_name in upload_chunks:
                    upload_chunks[file_name]["temp_file"].close()
                    temp_path = upload_chunks[file_name]["temp_path"]
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
            except OSError as e:
                debug_me(f"Error during cleanup: {str(e)}")


def save_uploaded_file(
    instance: Instance,
    file_name: str,
    options: list,
    filters: list,
    plex_title: str,
    plex_year: int,
    upload_chunks: dict,
    filename_pattern: re.Pattern,
    check_image_orientation_func,
    sort_key_func
):
    """
    Process the uploaded file from temp storage.

    Args:
        instance: Instance object for web notifications
        file_name: Name of the uploaded file
        filters: List of filters to apply
        plex_title: Optional title override
        plex_year: Optional year override
        upload_chunks: Dictionary with temp file metadata
        filename_pattern: Regex pattern for validating filenames
        check_image_orientation_func: Function to check image orientation
        sort_key_func: Function to generate sort keys
    """
    from artwork_uploader import process_uploaded_artwork

    # Get the temp file path that was used during chunk uploads
    temp_upload_path = upload_chunks[file_name]["temp_path"]
    debug_me(f"Processing uploaded file {file_name} from temp path: {temp_upload_path}")

    # Move to a proper file location with correct filename for processing
    temp_zip_folder = tempfile.mkdtemp()
    temp_zip_path = os.path.join(temp_zip_folder, file_name)
    
    import shutil
    shutil.move(temp_upload_path, temp_zip_path)
    debug_me(f"Moved {file_name} to temporary path: {temp_zip_folder}")

    debug_me(f"Saved ZIP file: {temp_zip_path}")

    update_log(instance, f"📦 {os.path.basename(temp_zip_path)} • Extracting ZIP file and parsing files...")
    # globals.scrapes_running += 1
    extracted_files, skipped, zip_title, zip_author, zip_source = extract_and_list_zip(
        instance,
        temp_zip_path,
        filename_pattern,
        filters,
        plex_title,
        plex_year,
        check_image_orientation_func,
        sort_key_func
    )
    if globals.cancel_scrape:
        notify_web(instance, "progress_bar", {"message": "Parsing aborted by user...", "percent": 100})#, "bar_type": bar_type, "bar_speed": bar_speed})
        update_log(instance, f"🛑 {os.path.basename(temp_zip_path)} • ZIP file parsing aborted by user")
        update_status(instance, f"ZIP file parsing aborted by user", color=StatusColor.WARNING.value)
        globals.scrapes_running -= 1
        if globals.scrapes_running <= 0:
            globals.scrapes_running = 0
            globals.cancel_scrape = False
            notify_web(instance, "scrape_state", { "running": False, "type": "upload" })
            notify_web(instance, "element_disable", { "element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False })
        return

    # Delete the ZIP file after extraction
    try:
        os.remove(temp_zip_path)
        os.rmdir(temp_zip_folder)
        debug_me(f"Deleted temporary ZIP file: {temp_zip_path}")
    except Exception as e:
        debug_me(f"Error deleting temporary ZIP file: {e}")

    # globals.scrapes_running += 1
    process_uploaded_artwork(instance, extracted_files, skipped, zip_title, zip_author, zip_source, options, filters, plex_title, plex_year)
    
    if globals.cancel_scrape:
        update_status(instance, "Uploaded file processing canceled by user", color=StatusColor.WARNING.value)
    else:
        update_status(instance, "Finished processing uploaded file", color=StatusColor.SUCCESS.value)
    
    globals.scrapes_running -= 1
    if globals.scrapes_running <= 0:
        globals.scrapes_running = 0
        globals.cancel_scrape = False
        notify_web(instance, "scrape_state", { "running": False, "type": "upload" })
        notify_web(instance, "element_disable", { "element": ["scrape_url", "scrape_button", "bulk_button"], "mode": False })



def extract_and_list_zip(
    instance: Instance,
    zip_path: str,
    filename_pattern: re.Pattern,
    filters: list,
    plex_title: str,
    plex_year: int,
    check_image_orientation_func,
    sort_key_func
) -> tuple[list, int, str, str, str]:
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
    file_list = []
    zip_title = ""
    zip_author = ""
    filtered_files = 0
    errored_files = 0

    debug_me(f"Extracting ZIP file: {zip_path} to {extract_dir}")

    # For ThePosterDB, extract title and author from filename
    pattern = r"^(?P<title>.+?)\s+set by\s+(?P<author>.+?)\s*-"
    match = re.search(pattern, os.path.basename(zip_path), re.IGNORECASE)
    if match:
        zip_source = ScraperSource.THEPOSTERDB.value
        zip_title = match.group("title").strip()
        zip_author = match.group("author").strip()
        debug_me(f"Detected ThePosterDB source")
        debug_me(f"Detected ZIP title: {zip_title}")
        debug_me(f"Detected ZIP author: {zip_author}")
    else:
        zip_source = ScraperSource.MEDIUX.value
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # Pre-process the file list to determine source and extract valid files
        zip_infos = [zip_info for zip_info in zip_ref.infolist() if os.path.basename(zip_info.filename) and not os.path.basename(zip_info.filename).startswith(".") and os.path.basename(zip_info.filename) not in {"ds_store", "__macosx"}]
        total_files_in_zip = len(zip_infos)
        
        update_status(instance, "Extracting ZIP file...", "info", sticky=True, spinner=True)
        notify_web(instance, "progress_bar", { "percent": 0, "message": "Parsing...", "bar_type": "main", "bar_speed": "fast" })
       
        identified_media_map = {}

        for n, zip_info in enumerate(zip_infos, 1):
            if globals.cancel_scrape:
                break
            filename = os.path.basename(zip_info.filename)  # Get filename only (ignore paths)
            debug_me(f"{n} / {total_files_in_zip} • Processing '{filename}'")
            percent = (n/total_files_in_zip)*100 if total_files_in_zip > 0 else 0
            notify_web(instance, "progress_bar", { "percent": percent, "message": f"Parsing {n} of {total_files_in_zip} • {filename}", "bar_type": "main", "bar_speed": "fast" })

            # Mediux ZIP files contain a source.txt file with metadata, we obtain title and author from there
            if filename == "source.txt":
                debug_me("Detected Mediux source")
                zip_source = ScraperSource.MEDIUX.value
                with zip_ref.open(zip_info) as source, open(os.path.join(extract_dir, "source.txt"), "wb") as target:
                    target.write(source.read())
                with open(os.path.join(extract_dir, "source.txt"), "r", encoding="utf-8") as source_file:
                    for line in source_file:
                        if line.startswith("Title:"):
                            zip_title = line.split("Title:")[1].strip()
                            debug_me(f"Detected ZIP title: {zip_title}")
                        if line.startswith("Author:"):
                            zip_author = line.split("Author:")[1].strip()
                            debug_me(f"Detected ZIP author: {zip_author}")
                            break
                os.remove(os.path.join(extract_dir, "source.txt"))  # Clean up source.txt after obtaining author info
                
            elif filename_pattern.match(filename):
                full_path = os.path.join(extract_dir, filename)

                with zip_ref.open(zip_info) as source, open(full_path, "wb") as target:
                    target.write(source.read())

                md5 = utils.calculate_file_md5(full_path)

                # Obtain artwork title, year, media type, season, episode and artwork type by parsing the filename
                debug_me(f"Parsing artwork metadata from filename: {filename}")
                artwork = parse_title(os.path.splitext(filename)[0])

                if artwork["media"] == "unable_to_parse":
                    update_log(instance, f"❌ {filename} • {zip_author} | Unable to parse file, formate unrecognized")
                    errored_files += 1
                    continue
                
                # We start building a Title -> Media map with the media type (Movie, TV, Collection) correctly parsed by parse_title
                if artwork["media"] != "Unknown" and artwork["title"] not in identified_media_map:
                    identified_media_map[artwork["title"]] = artwork["media"]

                # Override title and year if provided
                artwork["title"] = plex_title if plex_title else artwork["title"]
                artwork["year"] = plex_year if plex_year else artwork.get("year")
                # Add additional metadata
                artwork["source"] = zip_source
                artwork["path"] = full_path
                artwork["checksum"] = md5
                artwork["id"] = "Upload"
                artwork["author"] = zip_author
                # Determine media type via Plex lookup if not a collection, find TMDb ID, title
                # and year in the process for better matching later when processing artwork items
                if artwork["media"] != "Collection":
                    media_type, tmdb_id, title, year = globals.plex.movie_or_show(artwork.get('title'), artwork.get('year'))
                    if media_type == "unavailable" or "Error" in media_type:
                        # Mediux and TPDB replace colons with hyphens in titles, so revert that for lookup, and also remove ellipses
                        artwork["title"] = re.sub(r'-', '', artwork.get('title')).replace('...', '').strip()
                        media_type, tmdb_id, title, year = globals.plex.movie_or_show(artwork.get('title'), artwork.get('year'))
                        if media_type == "DNSError":
                            update_log(instance, f"❌ {filename} • {zip_author} | Error searching Plex: Cannot resolve server name")
                            errored_files += 1
                            continue
                        elif media_type == "ConnectionError":
                            update_log(instance, f"❌ {filename} • {zip_author} | Error searching Plex: Connection error")
                            errored_files += 1
                            continue
                        elif media_type == "TimeoutError":
                            update_log(instance, f"❌ {filename} • {zip_author} | Error searching Plex: Timed out")
                            errored_files += 1
                            continue
                        elif media_type == "Error":
                            update_log(instance, f"❌ {filename} • {zip_author} | Error searching Plex")
                            errored_files += 1
                            continue

                    # If we got a result from movie_or_show, we use that media type and we update the identified media map because the movie_or_show method is more accurate
                    if media_type != "unavailable":
                        artwork["media"] = media_type
                        identified_media_map[artwork["title"]] = media_type

                    # If we got "unavailable" from movie_or_show and we've already identified that title as a certain media type from another file, we use that
                    elif artwork["title"] in identified_media_map:
                        artwork["media"] = identified_media_map[artwork["title"]]

                    # Otherwise we set it to "unavailable"
                    # If we got "unavailable" from movie_or_show and we got "Unknown" from parse_title, we set it to "unavailable"
                    elif media_type == "unavailable" and artwork["media"] == "Unknown":
                        artwork["media"] = media_type
                    # If we get here and none of fhe above conditions are met, we have kept whatever media_type was determined by parse_title

                    artwork["title"] = title if title and title != artwork.get('title') else artwork.get('title')
                    artwork["tmdb_id"] = tmdb_id
                    if artwork.get('year') is None and year is not None:
                        artwork['year'] = year
                if artwork['media'] == "TV Show":
                    if artwork['season'] is None:
                        artwork['season'] = "Cover"
                        artwork['file_type'] = "show_cover"
                    if artwork['season'] == "Cover" and check_image_orientation_func(artwork["path"]) == "landscape":
                        artwork['season'] = "Backdrop"
                        artwork['file_type'] = "background"
                if artwork['media'] == "Movie":
                    if check_image_orientation_func(artwork["path"]) == "landscape":
                        artwork['file_type'] = "background"
                    elif artwork['file_type'] == "square_art" or check_image_orientation_func(artwork["path"]) == "square":
                        artwork['file_type'] = "square_art"
                    else:
                        artwork['file_type'] = "movie_poster"
                if artwork['media'] == "Collection":
                    if check_image_orientation_func(artwork["path"]) == "landscape":
                        artwork['file_type'] = "background"
                    elif check_image_orientation_func(artwork["path"]) == "square":
                        artwork['file_type'] = "square_art"
                if artwork['media'] == "unavailable":
                    if check_image_orientation_func(artwork["path"]) == "landscape":
                        artwork['file_type'] = "background"
                    elif check_image_orientation_func(artwork["path"]) == "square" or "OST" in artwork["path"]:
                        artwork['file_type'] = "square_art"
                    elif artwork['file_type'] == "season_cover":
                        artwork['media'] = "TV Show"
                    else:
                        # If we get to this point, there is no way to determine if it's a TV show or Movie, so default to poster
                        # However this won't pass any filters (becuase it's either "movie_poster" or "show_cover"), so this artwork won't be processed further
                        artwork['file_type'] = "poster"  

                # Check for filters and exclusions
                if not filters or artwork["file_type"] in filters:
                    debug_me(
                        f"✅ Including {artwork["file_type"].replace('_', ' ')} "
                        f"for '{artwork['title']}"
                        + (f" ({artwork['year']})'" if artwork['year'] is not None else "")
                        + (f", Season {artwork['season']}" if isinstance(artwork['season'], int) else "")
                        + (f", Episode {artwork['episode']}" if isinstance(artwork['episode'], int) else "")
                        + f". Type is {artwork['file_type']}."
                    )

                    file_list.append(artwork)
                else:
                    debug_me(
                        f"⏩ Skipping {artwork["file_type"].replace('_', ' ')} "
                        f"for '{artwork['title']}"
                        + (f" ({artwork['year']})'" if artwork['year'] is not None else "")
                        + (f", Season {artwork['season']}" if isinstance(artwork['season'], int) else "")
                        + (f", Episode {artwork['episode']}" if isinstance(artwork['episode'], int) else "")
                        + f" based on filters. Type is {artwork['file_type']} and filters are {filters}."
                    )
                    filtered_files += 1

    # Final clean-up in an effort to leave as few assets as possible unidentified
    final_file_list = []
    tv_sq_art = 0
    for artwork in file_list:
        # If the media type was not identified for a file but later we identified the title and
        # added it to the identified_media_map, we go back and update all assets for that same title
        if artwork["media"] == "unavailable" and artwork["title"] in identified_media_map:
            artwork["media"] = identified_media_map[artwork["title"]]
        # If the season and espisode are None but we identified it as a TV Show
        # then this means the asset is a show cover
        if artwork["season"] is None and artwork["episode"] is None and artwork["media"] == MediaType.TV_SHOW.value:
            artwork["season"] = "Cover"
            artwork["file_type"] = FileType.SHOW_COVER.value
        # We tag the square_art assets sequentially in their "season" field so that
        # the UploadProcessor can process the first one and decide what to do with the rest
        if artwork["season"] == "SquareArt":
            artwork["season"] = f"SquareArt_{tv_sq_art}"
            tv_sq_art += 1
        
        final_file_list.append(artwork)

    total_files = len(os.listdir(extract_dir))

    sorted_data = sorted(final_file_list, key=sort_key_func)

    debug_me(f"❌ Encountered {errored_files} error(s) parsing filenames")
    debug_me(f"⏩ Skipped {filtered_files} assets(s) out of {total_files} based on filters).")
    debug_me(f"✅ Included {len(sorted_data)} assets:")
    debug_me(sorted_data)

    return sorted_data, filtered_files, zip_title, zip_author, zip_source


def start_web_server(web_app, web_host: str, web_port: int, debug: bool = False):
    """
    Start the Flask web server.

    Args:
        web_app: Flask application instance
        web_host: Host to bind to
        web_port: Port to bind to
        debug: Whether to run in debug mode
    """
    debug_me("Initiating web server")
    flask.cli.show_server_banner = lambda *args: None
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    globals.web_socket.run(
        web_app, 
        host=web_host, 
        port=web_port, 
        debug=debug, 
        allow_unsafe_werkzeug=True
    )
