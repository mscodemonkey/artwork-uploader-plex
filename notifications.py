import globals
from instance import Instance

bootstrap_colors = {
    'primary': {
        'bg': '#0d6efd',
        'fg': '#ffffff',
        'ansi': '\033[0m'  # Set foreground to default
    },
    'secondary': {
        'bg': '#6c757d',
        'fg': '#ffffff',
        'ansi': '\033[36m'  # Set foreground to cyan
    },
    'success': {
        'bg': '#198754',
        'fg': '#ffffff',
        'ansi': '\033[32m',  # Set foreground to green
        "icon": "check-circle"
    },
    'danger': {
        'bg': '#dc3545',
        'fg': '#ffffff',
        'ansi': '\033[31m',  # Set foreground to red
        "icon": "exclamation-triangle"
    },
    'warning': {
        'bg': '#ffc107',
        'fg': '#212529',
        'ansi': '\033[35m',  # Set foreground to magenta
        "icon": "exclamation-circle-fill"
    },
    'info': {
        'bg': '#0dcaf0',
        'fg': '#212529',
        'ansi': '\033[34m',  # Set foreground to blue
        "icon": "info-circle"
    },
    'light': {
        'bg': '#f8f9fa',
        'fg': '#212529',
        'ansi': '\033[33m'  # Set foreground to yellow
    },
    'dark': {
        'bg': '#212529',
        'fg': '#ffffff',
        'ansi': '\033[30m'  # Reset to default rather than forcing black
    }
}

def update_status(instance: Instance, message, color="primary", sticky=False, spinner=False, icon=None, cli = False):
    """Update the status label with a message and color."""

    if (instance.mode == "cli" and cli) or globals.debug:
        print(f"{bootstrap_colors.get(color, {}).get('ansi', None)}{message}\033[0m")
    if instance.mode == "web":
        notify_web(instance, "status_update",
                   {"message": message, "color": color, "sticky": sticky, "spinner": spinner, "icon": icon if icon else bootstrap_colors.get(color, {}).get('icon', None)})

def debug_me(message: str, title:str = None):
    if globals.debug:
        if title:
            print(f"\033[1m{bootstrap_colors.get('info').get('ansi')}[{title}] \033[0m{message}")
        else:
            print(f"\033[0m{message}")

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
    except:
        pass

def notify_web(instance: Instance, event, data_to_include = None):

    if instance.mode == "web":
        instance_data = {"instance_id": instance.id, "broadcast": instance.broadcast}
        merged_arguments = data_to_include | instance_data
        debug_me(merged_arguments, "notify_web")
        globals.web_socket.emit(event, merged_arguments)

