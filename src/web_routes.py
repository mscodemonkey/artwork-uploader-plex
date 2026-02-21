"""
Web routes and Socket.IO handlers for the Flask application.

This module contains all Flask routes and Socket.IO event handlers,
extracted from artwork_uploader.py for better organization and maintainability.

The routes are organized into:
- HTTP routes (Flask @app.route)
- Socket.IO event handlers (@socket.on)
- Helper functions for file uploads and processing
"""
import shutil

from utils.notifications import update_log, update_status, notify_web, debug_me, send_notification
from utils import utils
from services import UtilityService, AuthenticationService
from services import NotifyService
from processors.media_metadata import parse_title
from models.instance import Instance
from core.constants import SOURCE_MEDIUX, SOURCE_THEPOSTERDB
from core.config import Config
from core.exceptions import InvalidUrl, InvalidFlag
from core import globals
import base64
import os
import pprint
import re
import socket
import subprocess
import sys
import tempfile
import zipfile
from functools import wraps

from flask import render_template, send_from_directory, request, redirect, url_for, session
from packaging import version
from plexapi.server import PlexServer
from logging_config import get_logger

logger = get_logger(__name__)


SOURCE_TXT = "source.txt"


def is_ipv6_available():
    """
    Check if IPv6 is available on the system.

    Returns:
        bool: True if IPv6 is available, False otherwise
    """
    try:
        # Try to create an IPv6 socket and bind to the IPv6 loopback address
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as test_socket:
            try:
                test_socket.bind(('::1', 0))
                return True
            except OSError:
                return False
    except (OSError, AttributeError):
        # AF_INET6 not available or socket creation failed
        return False


def is_dual_stack_supported():
    """
    Test if binding to :: actually enables dual-stack (IPv4 + IPv6) listening.

    This is important for Windows compatibility where the IPV6_V6ONLY socket
    option might prevent dual-stack behavior.

    Returns:
        bool: True if :: binding supports both IPv4 and IPv6, False otherwise
    """
    # First check if IPv6 is available at all
    if not is_ipv6_available():
        return False

    try:
        # Create a test server socket bound to :: (all interfaces, IPv6)
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as server_socket:

            # Set socket options to allow reuse
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Try to disable IPV6_V6ONLY if possible (enables dual-stack)
            # This might not be available on all platforms
            try:
                server_socket.setsockopt(
                    socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except (OSError, AttributeError):
                # IPV6_V6ONLY not available or can't be set
                pass

            # Bind to :: on a random port
            server_socket.bind(('::', 0))
            server_socket.listen(1)

            # Get the port that was assigned
            port = server_socket.getsockname()[1]

            # Test results
            ipv4_works = False
            ipv6_works = False

            # Test IPv6 connection
            try:
                with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as ipv6_client:
                    ipv6_client.settimeout(1)
                    ipv6_client.connect(('::1', port))
                    ipv6_works = True
            except OSError:
                pass

            # Test IPv4 connection (this is the key test for dual-stack)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ipv4_client:
                    ipv4_client.settimeout(1)
                    ipv4_client.connect(('127.0.0.1', port))
                    ipv4_works = True
            except OSError:
                pass

            # Dual-stack works if both IPv4 and IPv6 connections succeeded
            return ipv4_works and ipv6_works
    except Exception as e:
        debug_me(
            f"Error testing dual-stack support: {e}", "is_dual_stack_supported")
        return False


def login_required(f):
    """Decorator to require authentication for routes."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get config from globals
        config = globals.config if hasattr(
            globals, 'config') and globals.config else None

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
                return redirect(url_for('home'))
            else:
                error = "Invalid username or password"

        return render_template("login.html", error=error)

    @web_app.route("/logout")
    def logout():
        """Handle user logout."""
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
        downloads_path = os.path.join(
            UtilityService.get_exe_dir(), 'downloads')
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
        run_bulk_import_scrape_in_thread,
        save_bulk_import_file,
        load_bulk_import_file,
        rename_bulk_import_file,
        delete_bulk_import_file,
        add_file_to_schedule_thread,
        update_scheduled_jobs,
        current_version,
        check_image_orientation,
        sort_key
    )

    # Temporary storage for chunked uploads
    # Changed from in-memory list to file handles for better memory efficiency with large uploads
    upload_chunks = {}

    @globals.web_socket.on("debug_mode")
    def debug_mode(data):
        """Report on debug mode status and toggle debug mode."""
        instance = Instance(data.get("instance_id"), "web")
        if data.get("action") == "get":
            logger.info(f"Reporting current debug mode: {'On' if globals.debug else 'Off'}")
            debug_me(f"Reporting current debug mode: {'On' if globals.debug else 'Off'}", "debug_mode")
            notify_web(instance, "debug_mode", {"debug": globals.debug})
        elif data.get("action") == "toggle":
            logger.info(f"Turning debug mode {'Off' if globals.debug else 'On'}")
            debug_me(f"Turning debug mode {'Off' if globals.debug else 'On'}", "debug_mode")
            notify_web(instance, "debug_mode", {"debug": not globals.debug})
            if globals.debug:
                globals.debug = False
            else:
                globals.debug = True

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
            subprocess.run([python_cmd, "-m", "pip", "install",
                           "-r", "requirements.txt"], check=True)

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
            update_status(Instance(broadcast=True),
                          "Update failed, restarting the app...", "danger")
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
                {"element": ["scrape_url", "scrape_button",
                             "bulk_button"], "mode": True}
            )
            process_scrape_url_from_web(instance, url)

    @globals.web_socket.on("start_bulk_import")
    def handle_bulk_import_from_web(data):
        """Handle bulk import request from web UI."""
        instance = Instance(data.get("instance_id"), "web")
        bulk_list = data.get("bulk_list").lower()
        filename = data.get("filename", "bulk_import.txt")
        scheduled = data.get("scheduled", False)
        run_bulk_import_scrape_in_thread(instance, bulk_list, filename, scheduled=scheduled)

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
            folder_path = globals.bulk_file_service.get_bulk_imports_directory()
            bulk_files = [f.name for f in folder_path.iterdir() if f.is_file()]
        except (FileNotFoundError, PermissionError) as e:
            debug_me(
                f"Error loading bulk file list: {e}", "load_bulk_filelist")
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
            update_log(instance, f"Created new bulk file: {filename}")
            notify_web(instance, "create_bulk_file", {
                       "created": True, "filename": filename})
            # Reload the file list
            folder_path = globals.bulk_file_service.get_bulk_imports_directory()
            bulk_files = [f.name for f in folder_path.iterdir() if f.is_file()]
            notify_web(instance, "load_bulk_filelist",
                       {"bulk_files": bulk_files})
        except Exception as e:
            update_status(instance, f"Error creating file: {str(e)}", "danger")
            notify_web(instance, "create_bulk_file", {
                       "created": False, "error": str(e)})

    @globals.web_socket.on("display_message")
    def display_message(data):
        """Log a debug message from the frontend."""
        instance = Instance(data.get("instance_id"), "web")
        debug_me(f"Received message from frontend: '{data.get('message')}' - Log level: '{data.get('level')}'", "display_message")
        if data.get("level") == "debug":
            debug_me(data.get("message"), data.get("title", "web_message"))
        elif data.get("level") == "log":
            update_log(instance, data.get("message"))

    @globals.web_socket.on("test_plex_connect")
    def test_plex_connect(data):
        """Test connectivity to Plex server."""

        def fail(status, log):
            update_log(instance, log)
            update_status(instance, status, "danger", False, False, "x-circle")
            notify_web(instance, "test_plex_connect", {"success": False, "status": status, "log": log})
            notify_web(instance, "element_disable", {"element": ["test_plex_btn"], "mode": False})

        instance = Instance(data.get("instance_id"), "web")
        instance.broadcast = True
        update_status(instance, "Testing connection to Plex server", "info", False, True)

        # Disable the test button to prevent multiple clicks
        notify_web(instance, "element_disable", {"element": ["test_plex_btn"], "mode": True})

        # Capture Plex settings form parameters
        url = data.get("url", "")
        debug_me(f"Obtained Plex URL: {url}", "test_plex_connect")
        token = data.get("token", "")
        debug_me(f"Obtained Plex token: {'*' * min(len(token), 8) if token else '(not set)'}", "test_plex_connect")
        tv_libs = data.get("tv_libs", "")
        debug_me(f"Obtained {len(tv_libs)} TV libraries: {tv_libs}", "test_plex_connect")
        movie_libs = data.get("movie_libs", "")
        debug_me(f"Obtained {len(movie_libs)} Movie libraries: {movie_libs}", "test_plex_connect")

        # Check for a valid Plex server URL and token
        url_pattern = r"^https?:\/\/((([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})|(\d{1,3}(\.\d{1,3}){3}))(:\d+)?(\/.*)?$"
        token_pattern = r"^[A-Za-z0-9_-]{20,}$"
        if not re.fullmatch(url_pattern, url):
            fail("Invalid Plex URL", f"Invalid Plex URL: {url}")
            return
        if not re.fullmatch(token_pattern, token):
            fail("Invalid Plex token", f"Invalid Plex token: {token}")
            return

        # Check connectivity to server
        try:
            plex_server = PlexServer(url, token, timeout=5)
        except Exception as e:
            if "NewConnectionError" in str(e):
                log = "Error connecting to Plex - Connection refused"
            elif "ConnectTimeoutError" in str(e) or "timed out" in str(e):
                log = "Error connecting to Plex - Timed out"
            elif "unauthorized" in str(e):
                log = "Error connecting to Plex - Invalid token"
            elif "NameResolutionError" in str(e):
                log = "Error connecting to Plex - Cannot resolve server name"
            elif "SSLError" in str(e):
                log = "Error connecting to Plex - SSL certificate validation failed"
            else:
                log = f"Unknown error connecting to Plex: {str(e)}"
            fail("Error connecting to Plex, check log for details", log)
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
            fail("Some libraries not found, check log for details.",
                 f"The following libraries could not be found: {', '.join(invalid_libs)}")
            return

        update_log(instance, "Successfully connected to Plex server")
        update_status(instance, "Successfully connected to Plex server", "success", False, False, "check2-circle")
        notify_web(instance, "element_disable", {"element": ["test_plex_btn"], "mode": False})
        notify_web(instance, "test_plex_connect", {"success": True})

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
        for idx, url in enumerate(urls):
            test_notification.add_url(url)
            debug_me(f"Sending test notification to URL #{idx + 1}", "test_notifications")
            url_success = test_notification.send_notification(notification_title, notification_message)
            success = success and url_success
            if url_success:
                debug_me(f"Test notification sent successfully to URL #{idx + 1}", "test_notifications")
                update_log(instance, f"Test notification sent successfully to URL #{idx + 1}")
                if len(urls) == 1:
                    update_status(instance, "Test notification sent successfully", "success", False, False, "check2-circle")
            else:
                failed += 1
                debug_me(f"Test notification failed to send to URL #{idx + 1}.", "test_notifications")
                update_log(instance, f"Test notification failed to send to URL #{idx + 1}")
                if len(urls) == 1:
                    update_status(instance, "Test notification failed to send", "danger", False, False, "x-circle")
            test_notification.clear_urls()
        if len(urls) > 1:
            if success and len(urls) > 1:
                debug_me("All test notifications sent successfully", "test_notifications")
                update_log(instance, "All test notifications sent successfully")
                update_status(instance, "All test notifications sent successfully", "success", False, False, "check2-circle")
            elif failed < len(urls):
                debug_me("Some test notifications failed to send", "test_notifications")
                update_log(instance, "Some test notifications failed to send")
                update_status(instance, "Some test notifications failed to send. Check logs for details.", "warning", False, False, "exclamation-triangle")
            else:
                debug_me("All test notifications failed to send", "test_notifications")
                update_log(instance, "All test notifications failed to send")
                update_status(instance, "All test notifications failed to send", "danger", False, False, "x-circle")
        notify_web(instance, "element_disable", {"element": ["test_notif_btn"], "mode": False})

    @globals.web_socket.on("detect_docker")
    def docker_detection(data):
        """Detects whether app is running in docker and informs frontend."""
        instance = Instance(data.get("instance_id"), "web")
        if globals.docker:
            logger.info("Docker environment detected")
            debug_me(f"Docker detected, Kometa asset path: '{config.kometa_base}', temp dir: '{config.temp_dir}'", "docker_detection")
            notify_web(instance, "docker_detected", {"docker": "true", "kometa_base": config.kometa_base, "temp_dir": config.temp_dir})
        else:
            notify_web(instance, "docker_detected", {"docker": "false"})

    @globals.web_socket.on("set_password")
    def set_password_web(data):
        """Set a new password for authentication."""
        instance = Instance(data.get("instance_id"), "web")

        try:
            username = data.get("username", "")
            password = data.get("password", "")

            if not username or not password:
                notify_web(instance, "set_password", {
                           "success": False, "error": "Username and password required"})
                return

            # Hash the password
            password_hash = AuthenticationService.hash_password(password)

            # Update config
            config.auth_username = username
            config.auth_password_hash = password_hash
            config.auth_enabled = True
            config.save()

            # Also update globals
            globals.config = config

            notify_web(instance, "set_password", {"success": True})
            update_log(
                instance, f"Authentication enabled for user '{username}'")
        except Exception as e:
            notify_web(instance, "set_password", {
                       "success": False, "error": str(e)})

    @globals.web_socket.on("save_config")
    def save_config_web(data):
        """Save configuration from web UI."""
        instance = Instance(data.get("instance_id"), "web")

        try:
            # Unpack the config dictionary into the local config
            for key, value in data.get("config").items():
                # Skip password_hash - it should only be set via set_password
                if key == "auth_password_hash":
                    continue
                setattr(config, key, value)
            config.save()

            # Also update globals
            globals.config = config

            # Reconnect to Plex because the Plex server or token might have changed
            update_log(
                instance, "Saving updated configuration and reconnecting to Plex")
            globals.plex.reconnect(config)
            notify_web(instance, "save_config", {
                       "saved": True, "config": vars(config)})
        except Exception as config_error:
            update_status(instance, str(config_error), color="danger")

    @globals.web_socket.on("delete_schedule")
    def delete_task_from_scheduler(data):
        """Delete a scheduled task."""
        if data.get("instance_id"):
            instance = Instance(data.get("instance_id"), "web")
            schedule_file = data.get("file")

            if schedule_file:
                # Get job ID from scheduler service
                job_id = globals.scheduler_service.get_job_id_by_file(
                    schedule_file)

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
                    notify_web(
                        instance,
                        "delete_schedule",
                        {"file": schedule_file,
                            "job_reference": job_id, "deleted": True}
                    )
                else:
                    notify_web(instance, "delete_schedule", {
                               "deleted": False, "job_id": job_id})

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
                    debug_me(
                        f"Error adding schedule: {e}", "add_tasks_to_scheduler")
                    raise

                # Start the scheduler if it's not already started
                globals.scheduler_service.start()

        except Exception as e:
            if globals.debug:
                debug_me(
                    f"Error in scheduler setup: {e}", "add_tasks_to_scheduler")
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
        """Handle chunked file upload - writes directly to temp file for memory efficiency."""
        instance = Instance(data.get("instance_id"), "web")

        file_name = data["fileName"]
        chunk_data = data["chunkData"]
        chunk_index = data["chunkIndex"]
        total_chunks = data["totalChunks"]

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

        # Decode and write chunk directly to disk
        try:
            decoded_chunk = base64.b64decode(chunk_data)
            upload_chunks[file_name]["temp_file"].write(decoded_chunk)
            upload_chunks[file_name]["chunks_received"] += 1
        except Exception as e:
            logger.error(
                f"Error decoding/writing chunk {chunk_index}: {e}", exc_info=True)
            # Cleanup temp file and state to avoid resource leaks and partial uploads
            try:
                if file_name in upload_chunks:
                    temp_file_obj = upload_chunks[file_name].get("temp_file")
                    temp_path = upload_chunks[file_name].get("temp_path")
                    if temp_file_obj is not None:
                        try:
                            temp_file_obj.close()
                        except Exception as close_err:
                            logger.warning(
                                f"Error closing temp file for {file_name}: {close_err}",
                                exc_info=True,
                            )
                    if temp_path and os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except OSError as remove_err:
                            logger.warning(
                                f"Error removing temp file {temp_path} for {file_name}: {remove_err}",
                                exc_info=True,
                            )
                    # Remove the upload entry so it does not appear partially complete
                    del upload_chunks[file_name]
            except Exception as cleanup_err:
                logger.error(
                    f"Error during cleanup after failed chunk {chunk_index} for {file_name}: {cleanup_err}",
                    exc_info=True,
                )

    @globals.web_socket.on("upload_complete")
    def handle_upload_complete(data):
        """Finalize the upload once all chunks are received."""
        file_name = data.get("fileName")
        filters = data.get("filters")
        plex_year = data.get("plex_year")
        plex_title = data.get("plex_title")
        options = data.get("options")
        debug_me(
            f"Obtained options from web form: {options}", "handle_upload_complete")

        instance = Instance(data.get("instance_id"), "web")

        if file_name in upload_chunks and upload_chunks[file_name]["chunks_received"] == int(
                upload_chunks[file_name]["total_chunks"]
        ):
            debug_me(
                f"Upload complete for {file_name}, processing file...", "handle_upload_complete")

            # Close the temp file before processing
            upload_chunks[file_name]["temp_file"].close()

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
                # Delete temp file if it still exists
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError as remove_err:
                        logger.error(
                            f"Error removing temp file {temp_path}: {remove_err}")
                del upload_chunks[file_name]
            except (KeyError, OSError) as e:
                debug_me(f"Error during cleanup: {e}", "handle_upload_complete")
        else:
            chunks_received = upload_chunks[file_name]["chunks_received"] if file_name in upload_chunks else 0
            expected_chunks = upload_chunks[file_name]["total_chunks"] if file_name in upload_chunks else 0
            debug_me(
                f'Upload complete event received for {file_name}, but with '
                f'{chunks_received} of {expected_chunks}, some chunks are missing.',
                "handle_upload_complete"
            )
            try:
                # Clean up temp file
                if file_name in upload_chunks:
                    upload_chunks[file_name]["temp_file"].close()
                    temp_path = upload_chunks[file_name]["temp_path"]
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except OSError as remove_err:
                            logger.error(
                                f"Error removing temp file {temp_path}: {remove_err}")
                del upload_chunks[file_name]
            except (KeyError, OSError) as e:
                debug_me(f"Error during cleanup: {e}", "handle_upload_complete")


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
        options: List of options to apply
        filters: List of filters to apply
        plex_title: Optional title override
        plex_year: Optional year override
        upload_chunks: Dictionary with temp file info
        filename_pattern: Regex pattern for validating filenames
        check_image_orientation_func: Function to check image orientation
        sort_key_func: Function to generate sort keys
    """
    from artwork_uploader import process_uploaded_artwork

    # Get the temp file path that was written during chunk upload
    temp_upload_path = upload_chunks[file_name]["temp_path"]
    debug_me(
        f"Processing uploaded file {file_name} from temp path: {temp_upload_path}", "save_uploaded_file")

    # Move to a proper temp location with correct filename for processing
    temp_zip_folder = tempfile.mkdtemp()
    temp_zip_path = os.path.join(temp_zip_folder, file_name)

    # Move/rename the upload temp file to processing location
    try:
        shutil.move(temp_upload_path, temp_zip_path)
    except OSError as e:
        debug_me(
            f"Failed to move uploaded file from {temp_upload_path} to {temp_zip_path}: {e}",
            "save_uploaded_file",
        )
        # Best-effort cleanup of the temporary zip folder created for processing
        try:
            os.rmdir(temp_zip_folder)
        except Exception:
            # Ignore cleanup errors here to avoid masking the original exception
            pass
        # Re-raise so callers can handle the failure as before
        raise

    debug_me(f"Moved uploaded file to: {temp_zip_path}", "save_uploaded_file")

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

    # Delete the ZIP file after extraction
    try:
        os.remove(temp_zip_path)
        os.rmdir(temp_zip_folder)
        debug_me(
            f"Deleted temporary ZIP file: {temp_zip_path}", "save_uploaded_file")
    except Exception as e:
        debug_me(
            f"Error deleting temporary ZIP file: {e}", "save_uploaded_file")

    process_uploaded_artwork(instance, extracted_files, skipped, zip_title, zip_author, zip_source,
                             options, filters, plex_title, plex_year)

    notify_web(instance, "upload_complete", {"files": extracted_files})
    update_status(instance, "Finished processing uploaded file.",
                  color="success")


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
        instance: Instance object for web notifications
        zip_path: Path to the ZIP file
        filename_pattern: Regex pattern for validating filenames
        filters: List of artwork type filters to apply
        plex_title: Optional title override
        plex_year: Optional year override
        check_image_orientation_func: Function to check image orientation
        sort_key_func: Function to generate sort keys

    Returns:
        Tuple of (artwork list, skipped count, zip title, zip author, zip source)
    """
    extract_dir = tempfile.mkdtemp()
    file_list = []
    zip_source = SOURCE_THEPOSTERDB
    zip_title = None
    zip_author = None
    filtered_files = 0

    debug_me(
        f"Extracting ZIP file: {zip_path} to {extract_dir}", "extract_and_list_zip")

    # For ThePosterDB, extract title and author from filename
    pattern = r"^(?P<title>.+?)\s+set by\s+(?P<author>.+?)\s*-"
    match = re.search(pattern, os.path.basename(zip_path), re.IGNORECASE)
    if match:
        zip_title = match.group("title").strip()
        zip_author = match.group("author").strip()
        debug_me(f"Detected ThePosterDB source", "extract_and_list_zip")
        debug_me(f"Detected ZIP title: {zip_title}", "extract_and_list_zip")
        debug_me(f"Detected ZIP author: {zip_author}", "extract_and_list_zip")
    else:
        zip_source = SOURCE_MEDIUX

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # Pre-process the file list to determine source and extract valid files
        zip_infos = [
            zip_info for zip_info in zip_ref.infolist()
            if os.path.basename(zip_info.filename)
            and not os.path.basename(zip_info.filename).startswith(".")
            and os.path.basename(zip_info.filename).lower() not in {"ds_store", "__macosx"}
        ]
        total_files_in_zip = len(zip_infos)

        update_status(instance, "Extracting ZIP file...", "info", sticky=True, spinner=True)
        for n, zip_info in enumerate(zip_infos, 1):
            filename = os.path.basename(zip_info.filename)
            debug_me(f"{n} / {total_files_in_zip} - Processing '{filename}'", "extract_and_list_zip")
            percent = (n / total_files_in_zip) * 100 if total_files_in_zip > 0 else 0
            message = f"{n} / {total_files_in_zip} ({round(percent)}%)"
            notify_web(instance, "progress_bar", {"percent": percent, "message": message})

            # Mediux ZIP files contain a source.txt file with metadata
            if filename == SOURCE_TXT:
                debug_me("Detected Mediux source", "extract_and_list_zip")
                zip_source = SOURCE_MEDIUX
                with zip_ref.open(zip_info) as source, open(os.path.join(extract_dir, SOURCE_TXT), "wb") as target:
                    target.write(source.read())
                with open(os.path.join(extract_dir, SOURCE_TXT), "r", encoding="utf-8") as source_file:
                    for line in source_file:
                        if line.startswith("Title:"):
                            zip_title = line.split("Title:")[1].strip()
                            debug_me(f"Detected ZIP title: {zip_title}", "extract_and_list_zip")
                        if line.startswith("Author:"):
                            zip_author = line.split("Author:")[1].strip()
                            debug_me(f"Detected ZIP author: {zip_author}", "extract_and_list_zip")
                            break
                os.remove(os.path.join(extract_dir, SOURCE_TXT))

            elif filename_pattern.match(filename):
                full_path = os.path.join(extract_dir, filename)

                with zip_ref.open(zip_info) as source, open(full_path, "wb") as target:
                    target.write(source.read())

                md5 = utils.calculate_file_md5(full_path)

                # Obtain artwork title, year, media type, season, episode and artwork type by parsing the filename
                debug_me(f"Parsing artwork metadata from filename: {filename}", "extract_and_list_zip")
                artwork = parse_title(os.path.splitext(filename)[0])
                # Override title and year if provided
                artwork["title"] = plex_title if plex_title else artwork["title"]
                artwork["year"] = plex_year if plex_year else artwork.get("year")
                # Add additional metadata
                artwork["source"] = zip_source
                artwork["path"] = full_path
                artwork["checksum"] = md5
                artwork["id"] = "Upload"
                artwork["author"] = zip_author
                # Determine media type via Plex lookup if not a collection
                if artwork["media"] != "Collection":
                    media_type, tmdb_id, title, year = globals.plex.movie_or_show(
                        artwork.get('title'), artwork.get('year'))
                    if media_type is None:
                        # Mediux and TPDB replace colons with hyphens in titles, so revert that for lookup, and also remove ellipses
                        artwork["title"] = re.sub(r'-', '', artwork.get('title')).replace('...', '').strip()
                        media_type, tmdb_id, title, year = globals.plex.movie_or_show(
                            artwork.get('title'), artwork.get('year'))
                    artwork["media"] = media_type if media_type else "unavailable"
                    artwork["title"] = title if title and title != artwork.get('title') else artwork.get('title')
                    artwork["tmdb_id"] = tmdb_id
                    if artwork.get('year') is None and year is not None:
                        artwork['year'] = year
                if artwork['media'] == "TV Show":
                    if artwork['season'] is None:
                        artwork['season'] = "Cover"
                        artwork['type'] = "show_cover"
                    if artwork['season'] == "Cover" and check_image_orientation_func(artwork["path"]) == "landscape":
                        artwork['season'] = "Backdrop"
                        artwork['type'] = "background"
                if artwork['media'] == "Movie":
                    if check_image_orientation_func(artwork["path"]) == "landscape":
                        artwork['type'] = "background"
                    else:
                        artwork['type'] = "movie_poster"
                if artwork['media'] == "Collection":
                    if check_image_orientation_func(artwork["path"]) == "landscape":
                        artwork['type'] = "background"
                if artwork['media'] == "unavailable":
                    if check_image_orientation_func(artwork["path"]) == "landscape":
                        artwork['type'] = "background"
                    if artwork['type'] == "season_cover":
                        artwork['media'] = "TV Show"
                    else:
                        # If we get to this point, there is no way to determine if it's a TV show or Movie, so default to poster
                        # However this won't pass any filters (because it's either "movie_poster" or "show_cover"), so this artwork won't be processed further
                        artwork['type'] = "poster"

                # Check for filters and exclusions
                if not filters or artwork["type"] in filters:
                    debug_me(
                        f"Including {artwork['type'].replace('_', ' ')} "
                        f"for '{artwork['title']}"
                        + (f" ({artwork['year']})'" if artwork['year'] is not None else "'")
                        + (f", Season {artwork['season']}" if isinstance(artwork['season'], int) else "")
                        + (f", Episode {artwork['episode']}" if isinstance(artwork['episode'], int) else "")
                        + f". Type is {artwork['type']}.", "extract_and_list_zip"
                    )

                    file_list.append(artwork)
                else:
                    debug_me(
                        f"Skipping {artwork['type'].replace('_', ' ')} "
                        f"for '{artwork['title']}"
                        + (f" ({artwork['year']})'" if artwork['year'] is not None else "'")
                        + (f", Season {artwork['season']}" if isinstance(artwork['season'], int) else "")
                        + (f", Episode {artwork['episode']}" if isinstance(artwork['episode'], int) else "")
                        + f" based on filters. Type is {artwork['type']} and filters are {filters}.", "extract_and_list_zip"
                    )
                    filtered_files += 1

    total_files = len(os.listdir(extract_dir))

    sorted_data = sorted(file_list, key=sort_key_func)

    debug_me(f"Skipped {filtered_files} asset(s) out of {total_files} based on filters.", "extract_and_list_zip")
    debug_me(f"Included {len(sorted_data)} assets:", "extract_and_list_zip")
    if globals.debug:
        pprint.pprint(sorted_data)

    return sorted_data, filtered_files, zip_title, zip_author, zip_source


def start_web_server(web_app, web_port: int, debug: bool = False, ip_binding: str = "auto"):
    """
    Start the Flask web server with support for IPv4, IPv6, or dual-stack.

    Args:
        web_app: Flask application instance
        web_port: Port to bind to
        debug: Whether to run in debug mode
        ip_binding: IP binding mode - "auto" (dual-stack), "ipv4", or "ipv6"
    """
    # Determine the binding address based on ip_binding configuration
    ipv6_available = is_ipv6_available()

    if ip_binding == "auto":
        # Dual-stack: Listen on both IPv4 and IPv6
        if ipv6_available:
            logger.info("Checking dual-stack support...")
            dual_stack_supported = is_dual_stack_supported()
            if dual_stack_supported:
                # "::" enables both IPv4 and IPv6
                binding_host = "::"
                logger.info(
                    f"Starting web server on dual-stack (IPv4 and IPv6) at port {web_port}\n"
                    f"  - IPv4: http://127.0.0.1:{web_port}\n"
                    f"  - IPv6: http://[::1]:{web_port}")
            else:
                # Dual-stack not supported, fall back to IPv4 only
                binding_host = "0.0.0.0"
                logger.info(
                    f"Dual-stack not supported on this system, using IPv4 only at port {web_port}\n"
                    f"  - IPv4: http://127.0.0.1:{web_port}")
        else:
            # IPv6 not available, fall back to IPv4 only
            binding_host = "0.0.0.0"
            logger.info(
                f"IPv6 not available, using IPv4 only at port {web_port}\n"
                f"  - IPv4: http://127.0.0.1:{web_port}")
    elif ip_binding == "ipv6":
        # Prefer IPv6; may also accept IPv4 connections on dual-stack systems
        if ipv6_available:
            binding_host = "::"
            logger.info(
                f"Starting web server with IPv6 binding at port {web_port}\n"
                f"  - IPv6: http://[::1]:{web_port}\n"
                "    Note: On some systems this binding may also accept IPv4 connections due to dual-stack behavior.")
        else:
            # IPv6 requested but not available, fall back to IPv4
            binding_host = "0.0.0.0"
            logger.info(
                f"IPv6 requested but not available, falling back to IPv4 at port {web_port}\n"
                f"  - IPv4: http://127.0.0.1:{web_port}")
    else:
        # IPv4 only (default fallback)
        binding_host = "0.0.0.0"
        logger.info(
            f"Starting web server on IPv4 only at port {web_port}\n"
            f"  - IPv4: http://127.0.0.1:{web_port}")

    globals.web_socket.run(web_app, host=binding_host,
                           port=web_port, debug=debug)
