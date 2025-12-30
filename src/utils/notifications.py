from core import globals
from core.constants import BOOTSTRAP_COLORS, ANSI_RESET, ANSI_BOLD
from models.instance import Instance

# For backwards compatibility
bootstrap_colors = BOOTSTRAP_COLORS


def update_status(instance: Instance, message, color="primary", sticky=False, spinner=False, icon=None, cli=False):
    """Update the status label with a message and color."""

    if (instance.mode == "cli" and cli) or globals.debug:
        print(f"{bootstrap_colors.get(color, {}).get('ansi', None)}{message}\033[0m")
    if instance.mode == "web":
        notify_web(instance, "status_update",
                   {"message": message, "color": color, "sticky": sticky, "spinner": spinner,
                    "icon": icon if icon else bootstrap_colors.get(color, {}).get('icon', None)})


def debug_me(message: str, title: str = None):
    if globals.debug:
        if title:
            print(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('info').get('ansi')}[{title}] {ANSI_RESET}{message}")
        else:
            print(f"{ANSI_RESET}{message}")


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
        if instance.mode == "cli" or force_print or globals.debug:
            print(update_text)
        if instance.mode == "web":
            notify_web(instance, "log_update", {"message": update_text, "artwork_title": artwork_title})
    except Exception as e:
        # Fail silently for logging errors to avoid cascading failures
        if globals.debug:
            print(f"Error in update_log: {e}")


def notify_web(instance: Instance, event, data_to_include=None):
    if instance.mode == "web":
        instance_data = {"instance_id": instance.id, "broadcast": instance.broadcast}
        merged_arguments = data_to_include | instance_data
        debug_me(f"{ANSI_BOLD}{BOOTSTRAP_COLORS.get('info').get('ansi')}[{event}]{ANSI_RESET} {merged_arguments}",
                 "notify_web")
        globals.web_socket.emit(event, merged_arguments)
