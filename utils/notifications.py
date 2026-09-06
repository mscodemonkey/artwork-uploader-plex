import threading, inspect, os
from datetime import datetime
from typing import Optional
from core import globals
from pprint import pprint
from models.instance import Instance
from core.constants import BOOTSTRAP_COLORS, ANSI_RESET, ANSI_BOLD, DEFAULT_LOG_PATH, URL_SOURCE_MAP, URL_TYPE_MAP
from services.notify_service import NotifyService

# For backwards compatibility
bootstrap_colors = BOOTSTRAP_COLORS
print_lock = threading.Lock()

def update_status(instance: Instance, message, color="primary", sticky=False, spinner=False, icon=None, cli = False, width = None):
    """Update the status label with a message and color."""

    if instance.mode == "web":
        notify_web(
            instance=instance,
            event="status_update",
            data_to_include={
                "message": message,
                "color": color,
                "sticky": sticky,
                "spinner": spinner,
                "icon": icon if icon else BOOTSTRAP_COLORS.get(color, {}).get('icon', None),
                "width": width
            }
        )
    
    if (instance.mode == "cli" and cli) or globals.debug:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        message = f"[{timestamp}] {message}"
        with print_lock:
            print(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get(color, {}).get('ansi', None)}{message}{ANSI_RESET}")

def debug_me(message: str, title: str=None):
    with print_lock:
        if globals.debug:
            # Automatically infer the source of the call to the debug_me function
            # If it's a function inside a module (like start_web_server in web_routes.py) we get web_routes/start_web_server
            # If it's a method inside a class (like scrape for Scraper in scraper.py) we get Scrape/scrape
            frame = inspect.currentframe().f_back

            while frame:
                func_name = frame.f_code.co_name

                current_class = None
                if "self" in frame.f_locals:
                    current_class = frame.f_locals["self"].__class__.__name__
                elif "cls" in frame.f_locals:
                    obj = frame.f_locals["cls"]
                    current_class = getattr(obj, "__name__", obj.__class__.__name__)
                
                if func_name == "debug_callback" or current_class == "ProcessingCallbacks":
                    frame = frame.f_back
                else:
                    break
            
            if frame:
                func_name = frame.f_code.co_name

                file_path = frame.f_code.co_filename
                file_name = os.path.splitext(os.path.basename(file_path))[0]

                class_name = current_class
                if "self" in frame.f_locals:
                    class_name = frame.f_locals["self"].__class__.__name__

                elif "cls" in frame.f_locals:
                    obj = frame.f_locals["cls"]
                    class_name = getattr(obj, "__name__", obj.__class__.__name__)

                if func_name == "<module>":
                    source = f"{file_name}/__main__"
                elif class_name:
                    source = f"{class_name}/{func_name}"
                else:
                    source = f"{file_name}/{func_name}"

            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            if title: source = title
            if isinstance(message, (list, dict)):
                print(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('light').get('ansi')}", end="")
                pprint(message, sort_dicts=False, indent=2, compact=False)
                print(f"{ANSI_RESET}", end="")
            else:
                print(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('light').get('ansi')}[{timestamp}] [{source}] {ANSI_RESET}{message}")

def update_log(instance: Instance, update_text: str, broadcast: bool = False) -> None:

    """
    Updates the session log in the GUI.  The session log only exists while the app is running.

    Args:
        instance (Instance):
        update_text (str):
        artwork_title (str):
        force_print (bool)
    """
    try:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_message = f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('info').get('ansi')}[{timestamp}]{ANSI_RESET} {update_text}"
        log_file_message = f"[{timestamp}] {update_text}\n"
        with print_lock:
            print(log_message)
        run_log_file = current_log_file()
        if run_log_file:
            try:
                if not os.path.exists(run_log_file):
                    os.makedirs(DEFAULT_LOG_PATH, exist_ok=True)
                    with open(run_log_file, mode="xt", encoding="utf-8") as log_file:
                        log_file.write("-"*40 + f" {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} " + "-"*40 + "\n")
                with open(run_log_file, mode="at", buffering=1, encoding="utf-8") as log_file:
                    log_file.write(f"{log_file_message}")
            except Exception as e:
                debug_me(f"Unable to initialize log file {run_log_file}: {str(e)}")
                pass
        if instance.mode == "web":
            if not instance.broadcast and broadcast:
                instance.broadcast = broadcast
            notify_web(
                instance=instance,
                event="log_update",
                data_to_include={"message": update_text}
            )
    except Exception as e:
        # Fail silently for logging errors to avoid cascading failures
        if globals.debug:
            with print_lock:
                print(f"[{timestamp}] Error in update_log: {e}")

def notify_web(instance: Instance, event, data_to_include = None, silent=False):

    if instance.mode == "web":
        instance_data = {
            "instance_id": instance.id,
            "instance_mode": instance.mode,
            "broadcast": instance.broadcast
        }
        payload = data_to_include or {}
        merged_arguments = payload | instance_data
        debug_me(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('secondary').get('ansi')}[{event}]{ANSI_RESET} {merged_arguments if not silent else instance_data}")
        globals.web_socket.emit(event, merged_arguments)

def send_notification(instance: Instance, message: str, event: str = None) -> None:

    """
    Sends a notification to every configured channel subscribed to the given event.

    Args:
        instance (Instance):
        message (str):
        event (str): One of the NotificationEvent values. A channel only receives the
            message if this event is in its configured "events" list. If omitted, every
            configured channel is notified regardless of its event selection.

    Returns:
        None
    """
    try:
        channels = globals.config.apprise_urls
        if event is not None:
            channels = [channel for channel in channels if event in channel.get("events", [])]
        urls = [channel["url"] for channel in channels if channel.get("url")]

        if len(urls) > 0:
            notifier = NotifyService()
            notify_success = True
            for url in urls:
                notifier.add_url(url)
                url_success = notifier.send_notification("Artwork Uploader", message)
                if url_success:
                    debug_me(f"📢 Notification sent successfully for URL: {url}")
                    update_log(instance, f"📢 Notification sent successfully for URL: {url}")
                else:
                    debug_me(f"⚠️ Notification failed to send for URL: {url}")
                    update_log(instance, f"⚠️ Notification failed to send for URL: {url}")
                notify_success = notify_success and url_success
                notifier.clear_urls()
            if len(urls) > 1:
                if notify_success:
                    debug_me(f"✅ {len(urls)} notifications sent successfully.")
                    update_log(instance, f"✅ {len(urls)} notifications sent successfully.")
                elif not notify_success:
                    debug_me("⚠️ Some notifications failed to send. Check logs for details.")
                    update_log(instance, "⚠️ Some notifications failed to send. Check logs for details.")
    except Exception as e:
        debug_me(f"🚨 Error sending notification: {str(e)}")
        update_log(instance, f"🚨 Error sending notification: {str(e)}")

def current_log_file() -> Optional[str]:
    """The log file the run on this thread is writing to, or None outside a run."""
    return getattr(globals.run_log, "path", None)

def resume_log_file(path: Optional[str]) -> None:
    """
    Carry a run's log file onto the thread that continues the run.

    A run and its log normally share one thread. Two kinds of run continue on another: a
    webhook's retry ladder, where every attempt is a new Timer thread, and a chunked ZIP
    upload, where every chunk arrives on its own socket handler thread. They pass the path
    across the hop and call this on the far side, so the whole run lands in one file.
    """
    globals.run_log.path = path or None

def log_to_file(label: str) -> Optional[str]:
    """Open a log file for the run on this thread, named from `label`, and return its path.
    A run that already has one keeps it."""
    current = current_log_file()
    if current:
        debug_me(f"Logging is already active for this run")
        return current
    if ".txt" in label:
        log_label = f"bulk_{label.split(".txt")[0]}"
    elif "https" in label:
        clean_url = label.replace("https://", "").strip()
        parts = [p for p in clean_url.split("/") if p]
        if len(parts) >= 3:
            domain, asset_type, id = parts[0], parts[1], parts[2]
            source = URL_SOURCE_MAP.get(domain, "unknown_source")
            type = URL_TYPE_MAP.get(asset_type, "Unknown_type")
            url_type = type.get("label", "unknown_url_type")
            log_label = f"scrape_{source}_{url_type}_{id}"
    else:
        log_label = label

    log_label = log_label.lower()
    timestamp = datetime.now()
    log_filename = f"{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}_{log_label}"
    globals.run_log.path = os.path.join(DEFAULT_LOG_PATH, f"{log_filename}.log")
    debug_me(f"Setting log file for this run to '{globals.run_log.path}'")
    return globals.run_log.path
