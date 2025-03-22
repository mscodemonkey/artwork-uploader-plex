import globals
from instance import Instance


def update_status(instance: Instance, message, color="white", sticky=False, spinner=False, icon=None):
    """Update the status label with a message and color."""

    # Map the colours
    bootstrap_colors = {
        'primary': {
            'bg': '#0d6efd',  # background color
            'fg': '#ffffff'  # foreground color (text color)
        },
        'secondary': {
            'bg': '#6c757d',  # background color
            'fg': '#ffffff'  # foreground color (text color)
        },
        'success': {
            'bg': '#198754',  # background color
            'fg': '#ffffff',  # foreground color (text color)
            "icon": "check-circle"
        },
        'danger': {
            'bg': '#dc3545',  # background color
            'fg': '#ffffff',  # foreground color (text color)
            "icon": "exclamation-triangle"
        },
        'warning': {
            'bg': '#ffc107',  # background color
            'fg': '#212529',  # foreground color (text color)
            "icon": "exclamation-circle-fill"  # foreground color (text color)
        },
        'info': {
            'bg': '#0dcaf0',  # background color
            'fg': '#212529',  # foreground color (text color)
            "icon": "info-circle"
        },
        'light': {
            'bg': '#f8f9fa',  # background color
            'fg': '#212529'  # foreground color (text color)
        },
        'dark': {
            'bg': '#212529',  # background color
            'fg': '#ffffff'  # foreground color (text color)
        }
    }

    if instance.mode == "cli" or globals.debug:
        print(message)
    if instance.mode == "web":
        notify_web(instance, "status_update",
                   {"message": message, "color": color, "sticky": sticky, "spinner": spinner, "icon": icon if icon else bootstrap_colors.get(color, {}).get('icon', None)})

def debug_me(message: str):
    if globals.debug:
        print(message)


# * Threaded functions for scraping and setting posters ---
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
            print(instance.mode, update_text)
        if instance.mode == "web":
            notify_web(instance, "log_update", {"message": update_text, "artwork_title": artwork_title})
    except:
        pass

def notify_web(instance: Instance, event, data_to_include = None):

    if instance.mode == "web":
        instance_data = {"instance_id": instance.id}
        merged_arguments = data_to_include | instance_data
        debug_me(merged_arguments)
        globals.web_socket.emit(event, merged_arguments)

