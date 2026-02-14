from datetime import datetime
from core import globals
from pprint import pprint
from models.instance import Instance
from core.constants import BOOTSTRAP_COLORS, ANSI_RESET, ANSI_BOLD
from services.notify_service import NotifyService
import threading

# For backwards compatibility
bootstrap_colors = BOOTSTRAP_COLORS
print_lock = threading.Lock()

def update_status(instance: Instance, message, color="primary", sticky=False, spinner=False, icon=None, cli = False):
    """Update the status label with a message and color."""

    if instance.mode == "web":
        notify_web(instance, "status_update",
                   {"message": message, "color": color, "sticky": sticky, "spinner": spinner, "icon": icon if icon else BOOTSTRAP_COLORS.get(color, {}).get('icon', None)})
    if (instance.mode == "cli" and cli) or globals.debug:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        message = f"[{timestamp}] {message}"
        with print_lock:
            print(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get(color, {}).get('ansi', None)}{message}{ANSI_RESET}")

def debug_me(message: str, title:str = None):
    with print_lock:
        if globals.debug: 
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            if title:
                print(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('light').get('ansi')}[{timestamp}] [{title}] {ANSI_RESET}{message}")
            else:
                if isinstance(message, list) or isinstance(message, dict):
                    print(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('light').get('ansi')}", end="")
                    pprint(message) 
                    print(f"{ANSI_RESET}", end="")
                else:
                    print(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('light').get('ansi')}[{timestamp}] {ANSI_RESET}{message}")

def update_log(instance: Instance, update_text: str, artwork_title: str = None, force_print: bool = False) -> None:

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
#        if instance.mode == "cli" or force_print or globals.debug:
        with print_lock:
            print(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('info').get('ansi')}[{timestamp}]{ANSI_RESET} {update_text}")
        if instance.mode == "web":
            notify_web(instance, "log_update", {"message": update_text, "artwork_title": artwork_title})
    except Exception as e:
        # Fail silently for logging errors to avoid cascading failures
        if globals.debug:
            with print_lock:
                print(f"[{timestamp}] Error in update_log: {e}")

def notify_web(instance: Instance, event, data_to_include = None):

    if instance.mode == "web":
        instance_data = {"instance_id": instance.id, "instance_mode": instance.mode, "broadcast": instance.broadcast}
        merged_arguments = data_to_include | instance_data
        debug_me(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('secondary').get('ansi')}[{event}]{ANSI_RESET} {merged_arguments}", "notify_web")
        globals.web_socket.emit(event, merged_arguments)

def send_notification(instance: Instance, message: str) -> None:

    """
    Sends a notification using the NotifyService class.

    Args:
        instance (Instance):
        message (str):

    Returns:
        None
    """
    try:
        if len(globals.config.apprise_urls) > 0:
            notifier = NotifyService()
            notify_success = True
            for url in globals.config.apprise_urls:
                notifier.add_url(url)
                url_success = notifier.send_notification("Artwork Uploader", message)
                if url_success:
                    debug_me(f"📢 Notification sent successfully for URL: {url}", "send_notification")
                    update_log(instance, f"📢 Notification sent successfully for URL: {url}")
                else:
                    debug_me(f"⚠️ Notification failed to send for URL: {url}", "send_notification")
                    update_log(instance, f"⚠️ Notification failed to send for URL: {url}")
                notify_success = notify_success and url_success
                notifier.clear_urls()
            if len(globals.config.apprise_urls) > 1:
                if notify_success:
                    debug_me(f"✅ {len(globals.config.apprise_urls)} notifications sent successfully.", "send_notification")
                    update_log(instance, f"✅ {len(globals.config.apprise_urls)} notifications sent successfully.")
                elif not notify_success:
                    debug_me("⚠️ Some notifications failed to send. Check logs for details.", "send_notification")
                    update_log(instance, "⚠️ Some notifications failed to send. Check logs for details.")
    except Exception as e:
        debug_me(f"🚨 Error sending notification: {str(e)}", "send_notification")
        update_log(instance, f"🚨 Error sending notification: {str(e)}")
