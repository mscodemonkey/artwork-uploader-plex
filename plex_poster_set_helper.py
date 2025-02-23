import os
import time

import customtkinter as ctk
import tkinter as tk
import threading
import atexit
import sys
from PIL import Image

from config_exceptions import ConfigLoadError, ConfigSaveError
from plex_connector_exception import PlexConnectorException
import arguments
from config import Config
from upload_processor import UploadProcessor
from scraper import Scraper
import soup_utils
import tpdb
from utils import is_not_comment, parse_url_and_options, is_valid_url
from options import Options
from plex_connector import PlexConnector
from upload_processor_exceptions import CollectionNotFound, MovieNotFound, ShowNotFound, NotProcessedByFilter

# ! Interactive CLI mode flag
interactive_cli = False  # Set to False when building the executable with PyInstaller for it launches the GUI by default


# @ ---------------------- CORE FUNCTIONS ----------------------

def parse_bulk_file_from_cli(file_path):

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
                scrape_tpdb_user(parsed_url.url, parsed_url.options)
            else:
                scrape_and_upload(parsed_url.url, parsed_url.options)


def cleanup():

    """Function to handle cleanup tasks on exit."""

    print("-----------------------------------------------------------------------------------")

    try:
        if plex:
            print("Closing Plex server connection...")
        print("Exiting application. Cleanup complete.")
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


def resource_path(relative_path):
    """Get the absolute path to resource, works for dev and for PyInstaller bundle."""
    try:
        # PyInstaller creates a temp folder for the bundled app, MEIPASS is the path to that folder
        base_path = sys._MEIPASS
    except Exception:
        # If running in a normal Python environment, use the current working directory
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def get_full_path(relative_path):
    """Helper function to get the absolute path based on the script's location."""
    print("relative_path", relative_path)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, relative_path)


def update_status(message, color="white"):
    """Update the status label with a message and color."""
    app.after(0, lambda: status_label.configure(text=message, text_color=color))


def update_error(message):
    """Update the error label with a message, with a small delay."""
    # app.after(500, lambda: status_label.configure(text=message, text_color="red"))
    status_label.configure(text=message, text_color="red")


def clear_url():
    """Clear the URL entry field."""
    url_entry.delete(0, ctk.END)
    status_label.configure(text="URL cleared.", text_color="orange")


def set_default_tab(tabview):
    """Set the default tab to the Settings tab."""
    plex_base_url = base_url_entry.get()
    plex_token = token_entry.get()

    if plex_base_url and plex_token:
        tabview.set("Bulk Import")
    else:
        tabview.set("Settings")


def bind_context_menu(widget):
    """Bind the right-click context menu to the widget."""
    widget.bind("<Button-3>", clear_placeholder_on_right_click)
    widget.bind("<Control-1>", clear_placeholder_on_right_click)


def clear_placeholder_on_right_click(event):
    """Clears placeholder text and sets focus before showing the context menu."""
    widget = event.widget
    if isinstance(widget, ctk.CTkEntry) and widget.get() == "":
        widget.delete(0, tk.END)
    widget.focus()
    show_global_context_menu(event)


def show_global_context_menu(event):
    """Show the global context menu at the cursor position."""
    widget = event.widget
    global_context_menu.entryconfigure("Cut", command=lambda: widget.event_generate("<<Cut>>"))
    global_context_menu.entryconfigure("Copy", command=lambda: widget.event_generate("<<Copy>>"))
    global_context_menu.entryconfigure("Paste", command=lambda: widget.event_generate("<<Paste>>"))
    global_context_menu.tk_popup(event.x_root, event.y_root)


# * Configuration file I/O functions  ---


def save_config():

    """Save the configuration from the UI fields to the file and update the in-memory config."""

    global config

    # Set new vslues for the config, from the UI
    config.base_url = base_url_entry.get().strip()
    config.token = token_entry.get().strip()
    config.tv_library = [item.strip() for item in tv_library_text.get().strip().split(",")]
    config.movie_library =  [item.strip() for item in movie_library_text.get().strip().split(",")]
    config.mediux_filters =  mediux_filters_text.get().strip().split(", ")
    config.tpdb_filters =  tpdb_filters_text.get().strip().split(", ")
    config.bulk_txt = bulk_txt_entry.get().strip()

    try:
        config.save()
        update_status("Configuration saved successfully!", color="#E5A00D")
    except ConfigSaveError as config_save_error:
        update_status(f"Error saving config: {str(config_save_error)}", color="red")

    try:
        load_and_update_ui()
    except Exception as config_error:
        update_status(f"Error with config: {str(config_error)}", color="red")



def load_and_update_ui():
    """Load the configuration and update the UI fields."""

    global config

    if base_url_entry is not None:
        base_url_entry.delete(0, ctk.END)
        base_url_entry.insert(0, config.base_url if config.base_url is not None else "")

    if token_entry is not None:
        token_entry.delete(0, ctk.END)
        token_entry.insert(0, config.token if config.token is not None else "")

    if bulk_txt_entry is not None:
        bulk_txt_entry.delete(0, ctk.END)
        bulk_txt_entry.insert(0, config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt")

    if tv_library_text is not None:
        tv_library_text.delete(0, ctk.END)
        tv_library_text.insert(0, ", ".join(config.tv_library if config.tv_library else []))

    if movie_library_text is not None:
        movie_library_text.delete(0, ctk.END)
        movie_library_text.insert(0, ", ".join(config.movie_library if config.movie_library else []))

    if mediux_filters_text is not None:
        mediux_filters_text.delete(0, ctk.END)
        mediux_filters_text.insert(0, ", ".join(config.mediux_filters if config.mediux_filters else []))

    if tpdb_filters_text is not None:
        tpdb_filters_text.delete(0, ctk.END)
        tpdb_filters_text.insert(0, ", ".join(config.tpdb_filters if config.tpdb_filters else []))

    load_bulk_import_file()


# * Threaded functions for scraping and setting posters ---

def run_url_scrape_thread():
    """Run the URL scrape in a separate thread."""
    global scrape_button, clear_button, bulk_import_button
    url = url_entry.get()

    if not url or not is_valid_url(url):
        update_status("Please enter a valid URL.", color="red")
        return

    tabview.set("Session Log")
    scrape_button.configure(state="disabled")
    clear_button.configure(state="disabled")
    bulk_import_button.configure(state="disabled")

    threading.Thread(target=process_scrape_url_from_gui, args=(url,)).start()


def run_bulk_import_scrape_thread():

    """Run the bulk import scrape in a separate thread."""

    global bulk_import_button
    parsed_urls = []

    # Grab the bulk list from the version currently in the GUI (whether saved or not)
    bulk_import_list = bulk_import_text.get(1.0, ctk.END).strip().split("\n")

    # Loop through the import file and build a list of URLs and options
    # Ignoring any lines containing comments using # or //
    for line in bulk_import_list:
        if is_not_comment(line):
            parsed_url = parse_url_and_options(line)
            parsed_urls.append(parsed_url)

    if not parsed_urls:
        app.after(0, lambda: update_status("No bulk import entries found.", color="red"))
        return

    tabview.set("Session Log")
    scrape_button.configure(state="disabled")
    clear_button.configure(state="disabled")
    bulk_import_button.configure(state="disabled")

    # Pass the processing of the parsed URLs off to a thread
    threading.Thread(target=process_bulk_import_from_gui, args=(parsed_urls,)).start()


# UI Session Log
def clear_log():
    try:
        session_log_text.configure(state="normal")
        session_log_text.delete(1.0, "end")
        session_log_text.configure(state="disabled")
        update_status("Log cleared", color="#E5A00D")
    except:
        pass
    finally:
        app.after(1000, update_status, "", "#E5A00D")

def update_log(update_text: str) -> None:

    """
    Updates the session log in the GUI.  The session log only exists while the app is running.

    :param  update_text:    The text to append to the session log.  Will remain until cleared.
    :return: nothing
    """

    try:
        print(update_text)
        session_log_text.configure(state="normal")
        session_log_text.insert("end",f"{update_text}\n")
        session_log_text.configure(state="disabled")
    except:
        pass


# * Processing functions for scraping and setting posters from the GUI

def process_scrape_url_from_gui(url: str) -> None:

    """
    Process the URL and any options, then scrape for posters and updates the GUI with the results
    Now switches to the session log tab when you hit the button so that you can see the results as they happen

    :param      url: The URL to scrape.  Note that due to options, this may not be the only URL that we end up scraping!
    :return:    nothing
    """

    try:

        # Check if the Plex TV and movie libraries are configured
        if plex.tv_libraries is None or plex.movie_libraries is None:
            update_status("Plex setup incomplete. Please configure your settings.", color="red")
            return

        # Update the UI before we start
        update_status(f"Scraping: {url}", color="#E5A00D")

        # Process the URL and options passed from the UI
        parsed_line = parse_url_and_options(url)

        # Scrape the URL indicated, with the required options
        scrape_and_upload(parsed_line.url, parsed_line.options)

        # And update the UI when we're done
        update_status(f"Posters successfully set for: {url}", color="#E5A00D")

    except Exception as scraping_error:
        update_status(f"Error: {scraping_error}", color="red")

    finally:

        # Reset the buttons on the UI
        app.after(0, lambda: [
            scrape_button.configure(state="normal"),
            clear_button.configure(state="normal"),
            bulk_import_button.configure(state="normal"),
        ])


def process_bulk_import_from_gui(parsed_urls: list) -> None:

    """
    Process the bulk import scrape, based on the contents of the Bulk Import tab in the GUI.

    The bulk import list doesn't need to have been saved, it will use the list as it exists in the GUI currently.

    :param      parsed_urls:    The URLs to scrape.  These can be theposterdb poster, set or user URL or a mediux set URL.
    :return:    nothing
    """

    global plex

    try:

        # Check if plex setup returned valid values
        if plex.tv_libraries is None or plex.movie_libraries is None:
            update_status("Plex setup incomplete. Please configure your settings.", color="red")
            return

        for i, parsed_url in enumerate(parsed_urls):

            status_text = f"Processing item {i + 1} of {len(parsed_urls)}: {parsed_url.url}"
            update_status(status_text, color="#E5A00D")

            # Parse according to whether it's a user portfolio or poster / set URL
            if "/user/" in parsed_url.url:
                scrape_tpdb_user(parsed_url.url, parsed_url.options)
            else:
                scrape_and_upload(parsed_url.url, parsed_url.options)

            update_status(f"Completed: {parsed_url.url}", color="#E5A00D")


        update_status("Bulk import scraping completed.", color="#E5A00D")

    except Exception as e:

        update_status(f"Error during bulk import: {e}", color="red")

    finally:
        app.after(0, lambda: [
            scrape_button.configure(state="normal"),
            clear_button.configure(state="normal"),
            bulk_import_button.configure(state="normal"),
        ])


# * Bulk import file I/O functions ---

def load_bulk_import_file():

    """Load the bulk import file into the text area."""

    global config

    try:
        # Get the current bulk_txt value from the config
        bulk_txt_path = config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt"

        # Use get_exe_dir() to determine the correct path for both frozen and non-frozen cases
        bulk_txt_path = os.path.join(get_exe_dir(), bulk_txt_path)

        if not os.path.exists(bulk_txt_path):
            print(f"File does not exist: {bulk_txt_path}")
            bulk_import_text.delete(1.0, ctk.END)
            bulk_import_text.insert(ctk.END, "Bulk import file path is not set or file does not exist.")
            status_label.configure(text="Bulk import file path not set or file not found.", text_color="red")
            return

        with open(bulk_txt_path, "r", encoding="utf-8") as file:
            content = file.read()

        bulk_import_text.delete(1.0, ctk.END)
        bulk_import_text.insert(ctk.END, content)

    except FileNotFoundError:
        bulk_import_text.delete(1.0, ctk.END)
        bulk_import_text.insert(ctk.END, "File not found or empty.")
    except Exception as e:
        bulk_import_text.delete(1.0, ctk.END)
        bulk_import_text.insert(ctk.END, f"Error loading file: {str(e)}")


def save_bulk_import_file():
    """Save the bulk import text area content to a file relative to the executable location."""
    try:
        exe_path = get_exe_dir()
        bulk_txt_path = os.path.join(exe_path, config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt")

        os.makedirs(os.path.dirname(bulk_txt_path), exist_ok=True)

        with open(bulk_txt_path, "w", encoding="utf-8") as file:
            file.write(bulk_import_text.get(1.0, ctk.END).strip())

        status_label.configure(text="Bulk import file saved!", text_color="#E5A00D")
    except Exception as e:
        status_label.configure(
            text=f"Error saving bulk import file: {str(e)}", text_color="red"
        )


# * Button Creation ---

def create_button(container, text, command, color=None, primary=False, height=35):
    """Create a custom button with hover effects for a CustomTkinter GUI."""

    button_height = height
    button_fg = "#2A2B2B" if color else "#1C1E1E"
    button_border = "#484848"
    button_text_color = "#CECECE" if color else "#696969"
    plex_orange = "#E5A00D"

    if primary:
        button_fg = plex_orange
        button_text_color, button_border = "#1C1E1E", "#1C1E1E"

    button = ctk.CTkButton(
        container,
        text=text,
        command=command,
        border_width=1,
        text_color=button_text_color,
        fg_color=button_fg,
        border_color=button_border,
        hover_color="#333333",
        width=80,
        height=button_height,
        font=("Roboto", 13, "bold"),
    )

    def on_enter(event):
        """Change button appearance when mouse enters."""
        if color:
            button.configure(fg_color="#2A2B2B", text_color=lighten_color(color, 0.3),
                             border_color=lighten_color(color, 0.5))
        else:
            button.configure(fg_color="#1C1E1E", text_color=plex_orange, border_color=plex_orange)

    def on_leave(event):
        """Reset button appearance when mouse leaves."""
        if color:
            button.configure(fg_color="#2A2B2B", text_color="#CECECE", border_color=button_border)
        else:
            if primary:
                button.configure(fg_color=plex_orange, text_color="#1C1E1E", border_color="#1C1E1E")
            else:
                button.configure(fg_color="#1C1E1E", text_color="#696969", border_color=button_border)

    def lighten_color(color, amount=0.5):
        """Lighten a color by blending it with white."""
        hex_to_rgb = lambda c: tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
        r, g, b = hex_to_rgb(color)

        r = int(r + (255 - r) * amount)
        g = int(g + (255 - g) * amount)
        b = int(b + (255 - b) * amount)

        return f"#{r:02x}{g:02x}{b:02x}"

    button.bind("<Enter>", on_enter)
    button.bind("<Leave>", on_leave)

    return button


# * Main UI Creation function ---

def create_ui():
    """Create the main UI window."""
    global plex, app, global_context_menu, scrape_button, clear_button, mediux_filters_text, tpdb_filters_text, bulk_import_text, base_url_entry, token_entry,\
        status_label, url_entry, app, bulk_import_button, tv_library_text, movie_library_text, bulk_txt_entry, session_log_text, session_log_clear, tabview


    ctk.set_appearance_mode("dark")

    app.title("Plex Poster Upload Helper")
    app.geometry("850x600")
    app.iconbitmap(resource_path("icons/Plex.ico"))
    app.configure(fg_color="#2A2B2B")

    global_context_menu = tk.Menu(app, tearoff=0)
    global_context_menu.add_command(label="Cut")
    global_context_menu.add_command(label="Copy")
    global_context_menu.add_command(label="Paste")

    def open_url(url):
        """Open a URL in the default web browser."""
        import webbrowser
        webbrowser.open(url)

    # ! Create a frame for the link bar --
    link_bar = ctk.CTkFrame(app, fg_color="transparent")
    link_bar.pack(fill="x", pady=5, padx=10)

    # ? Link to Plex Media Server from the base URL
    base_url = config.base_url
    target_url = base_url if base_url else "https://www.plex.tv"

    plex_icon = ctk.CTkImage(light_image=Image.open(resource_path("icons/Plex.ico")), size=(24, 24))
    plex_icon_image = Image.open(resource_path("icons/Plex.ico"))

    icon_label = ctk.CTkLabel(link_bar, image=plex_icon, text="", anchor="w")
    icon_label.pack(side="left", padx=0, pady=0)
    url_text = base_url if base_url else "Plex Media Server"
    url_label = ctk.CTkLabel(link_bar, text=url_text, anchor="w", font=("Roboto", 14, "bold"), text_color="#CECECE")
    url_label.pack(side="left", padx=(5, 10))

    def on_hover_enter(event):
        app.config(cursor="hand2")
        rotated_image = plex_icon_image.rotate(15, expand=True)
        rotated_ctk_icon = ctk.CTkImage(light_image=rotated_image, size=(24, 24))
        icon_label.configure(image=rotated_ctk_icon)

    def on_hover_leave(event):
        app.config(cursor="")
        icon_label.configure(image=plex_icon)

    def on_click(event):
        open_url(target_url)

    for widget in (icon_label, url_label):
        widget.bind("<Enter>", on_hover_enter)
        widget.bind("<Leave>", on_hover_leave)
        widget.bind("<Button-1>", on_click)

    # ? Links to Mediux and ThePosterDB
    mediux_button = create_button(
        link_bar,
        text="MediUX.pro",
        command=lambda: open_url("https://mediux.pro"),
        color="#945af2",
        height=30
    )
    mediux_button.pack(side="right", padx=5)

    posterdb_button = create_button(
        link_bar,
        text="ThePosterDB",
        command=lambda: open_url("https://theposterdb.com"),
        color="#FA6940",
        height=30
    )
    posterdb_button.pack(side="right", padx=5)

    # ! Create Tabview --
    tabview = ctk.CTkTabview(app)
    tabview.pack(fill="both", expand=True, padx=20, pady=0)

    tabview.configure(
        fg_color="#2A2B2B",
        segmented_button_fg_color="#1C1E1E",
        segmented_button_selected_color="#915e06",
        segmented_button_selected_hover_color="#915e06",
        segmented_button_unselected_color="#1C1E1E",
        segmented_button_unselected_hover_color="#1C1E1E",
        text_color="#CECECE",
        text_color_disabled="#777777",
        border_color="#484848",
        border_width=2,
    )

    # ! Form row label hover
    LABEL_HOVER = "#878787"

    def on_hover_in(label):
        label.configure(text_color=LABEL_HOVER)

    def on_hover_out(label):
        label.configure(text_color="#696969")

        # ! Settings Tab --

    settings_tab = tabview.add("Settings")
    settings_tab.grid_columnconfigure(0, weight=0)
    settings_tab.grid_columnconfigure(1, weight=1)

    # Plex Base URL
    base_url_label = ctk.CTkLabel(settings_tab, text="Plex Base URL", text_color="#696969", font=("Roboto", 15))
    base_url_label.grid(row=0, column=0, pady=5, padx=10, sticky="w")
    base_url_entry = ctk.CTkEntry(settings_tab, placeholder_text="Enter Plex Base URL", fg_color="#1C1E1E",
                                  text_color="#A1A1A1", border_width=0, height=40)
    base_url_entry.grid(row=0, column=1, pady=5, padx=10, sticky="ew")
    base_url_entry.bind("<Enter>", lambda event: on_hover_in(base_url_label))
    base_url_entry.bind("<Leave>", lambda event: on_hover_out(base_url_label))
    bind_context_menu(base_url_entry)

    # Plex Token
    token_label = ctk.CTkLabel(settings_tab, text="Plex Token", text_color="#696969", font=("Roboto", 15))
    token_label.grid(row=1, column=0, pady=5, padx=10, sticky="w")
    token_entry = ctk.CTkEntry(settings_tab, placeholder_text="Enter Plex Token", fg_color="#1C1E1E",
                               text_color="#A1A1A1", border_width=0, height=40)
    token_entry.grid(row=1, column=1, pady=5, padx=10, sticky="ew")
    token_entry.bind("<Enter>", lambda event: on_hover_in(token_label))
    token_entry.bind("<Leave>", lambda event: on_hover_out(token_label))
    bind_context_menu(token_entry)

    # Bulk Import File
    bulk_txt_label = ctk.CTkLabel(settings_tab, text="Bulk Import File", text_color="#696969", font=("Roboto", 15))
    bulk_txt_label.grid(row=2, column=0, pady=5, padx=10, sticky="w")
    bulk_txt_entry = ctk.CTkEntry(settings_tab, placeholder_text="Enter bulk import file path", fg_color="#1C1E1E",
                                  text_color="#A1A1A1", border_width=0, height=40)
    bulk_txt_entry.grid(row=2, column=1, pady=5, padx=10, sticky="ew")
    bulk_txt_entry.bind("<Enter>", lambda event: on_hover_in(bulk_txt_label))
    bulk_txt_entry.bind("<Leave>", lambda event: on_hover_out(bulk_txt_label))
    bind_context_menu(bulk_txt_entry)

    # TV Library Names
    tv_library_label = ctk.CTkLabel(settings_tab, text="TV Library Names", text_color="#696969", font=("Roboto", 15))
    tv_library_label.grid(row=3, column=0, pady=5, padx=10, sticky="w")
    tv_library_text = ctk.CTkEntry(settings_tab, fg_color="#1C1E1E", text_color="#A1A1A1", border_width=0, height=40)
    tv_library_text.grid(row=3, column=1, pady=5, padx=10, sticky="ew")
    tv_library_text.bind("<Enter>", lambda event: on_hover_in(tv_library_label))
    tv_library_text.bind("<Leave>", lambda event: on_hover_out(tv_library_label))
    bind_context_menu(tv_library_text)

    # Movie Library Names
    movie_library_label = ctk.CTkLabel(settings_tab, text="Movie Library Names", text_color="#696969",
                                       font=("Roboto", 15))
    movie_library_label.grid(row=4, column=0, pady=5, padx=10, sticky="w")
    movie_library_text = ctk.CTkEntry(settings_tab, fg_color="#1C1E1E", text_color="#A1A1A1", border_width=0, height=40)
    movie_library_text.grid(row=4, column=1, pady=5, padx=10, sticky="ew")
    movie_library_text.bind("<Enter>", lambda event: on_hover_in(movie_library_label))
    movie_library_text.bind("<Leave>", lambda event: on_hover_out(movie_library_label))
    bind_context_menu(movie_library_text)

    # Mediux Filters
    mediux_filters_label = ctk.CTkLabel(settings_tab, text="MediuUX Filters", text_color="#696969", font=("Roboto", 15))
    mediux_filters_label.grid(row=5, column=0, pady=5, padx=10, sticky="w")
    mediux_filters_text = ctk.CTkEntry(settings_tab, fg_color="#1C1E1E", text_color="#A1A1A1", border_width=0,
                                       height=40)
    mediux_filters_text.grid(row=5, column=1, pady=5, padx=10, sticky="ew")
    mediux_filters_text.bind("<Enter>", lambda event: on_hover_in(mediux_filters_label))
    mediux_filters_text.bind("<Leave>", lambda event: on_hover_out(mediux_filters_label))
    bind_context_menu(mediux_filters_text)

    # TPDb Filters
    tpdb_filters_label = ctk.CTkLabel(settings_tab, text="TPDb Filters", text_color="#696969", font=("Roboto", 15))
    tpdb_filters_label.grid(row=6, column=0, pady=5, padx=10, sticky="w")
    tpdb_filters_text = ctk.CTkEntry(settings_tab, fg_color="#1C1E1E", text_color="#A1A1A1", border_width=0,
                                       height=40)
    tpdb_filters_text.grid(row=6, column=1, pady=5, padx=10, sticky="ew")
    tpdb_filters_text.bind("<Enter>", lambda event: on_hover_in(tpdb_filters_label))
    tpdb_filters_text.bind("<Leave>", lambda event: on_hover_out(tpdb_filters_label))
    bind_context_menu(tpdb_filters_text)

    settings_tab.grid_rowconfigure(0, weight=0)
    settings_tab.grid_rowconfigure(1, weight=0)
    settings_tab.grid_rowconfigure(2, weight=0)
    settings_tab.grid_rowconfigure(3, weight=0)
    settings_tab.grid_rowconfigure(4, weight=0)
    settings_tab.grid_rowconfigure(5, weight=0)
    settings_tab.grid_rowconfigure(6, weight=0)
    settings_tab.grid_rowconfigure(7, weight=1)

    # ? Load and Save Buttons (Anchored to the bottom)
    load_button = create_button(settings_tab, text="Reload", command=load_and_update_ui)
    load_button.grid(row=8, column=0, pady=5, padx=5, ipadx=30, sticky="ew")
    save_button = create_button(settings_tab, text="Save", command=save_config, primary=True)
    save_button.grid(row=8, column=1, pady=5, padx=5, sticky="ew")

    settings_tab.grid_rowconfigure(8, weight=0, minsize=40)

    # ! Bulk Import Tab --
    bulk_import_tab = tabview.add("Bulk Import")

    bulk_import_tab.grid_columnconfigure(0, weight=0)
    bulk_import_tab.grid_columnconfigure(1, weight=3)
    bulk_import_tab.grid_columnconfigure(2, weight=0)

    # bulk_import_label = ctk.CTkLabel(bulk_import_tab, text=f"Bulk Import Text", text_color="#CECECE")
    # bulk_import_label.grid(row=0, column=0, pady=5, padx=10, sticky="w")
    bulk_import_text = ctk.CTkTextbox(
        bulk_import_tab,
        height=15,
        wrap="none",
        state="normal",
        fg_color="#1C1E1E",
        text_color="#A1A1A1",
        font=("Courier", 14)
    )
    bulk_import_text.grid(row=1, column=0, padx=10, pady=5, sticky="nsew", columnspan=2)
    bind_context_menu(bulk_import_text)

    bulk_import_tab.grid_rowconfigure(0, weight=0)
    bulk_import_tab.grid_rowconfigure(1, weight=1)
    bulk_import_tab.grid_rowconfigure(2, weight=0)

    # Button row: Load, Save, Run buttons
    load_bulk_button = create_button(bulk_import_tab, text="Reload", command=load_bulk_import_file)
    load_bulk_button.grid(row=2, column=0, pady=5, padx=5, ipadx=30, sticky="ew")

    save_bulk_button = create_button(bulk_import_tab, text="Save", command=save_bulk_import_file)
    save_bulk_button.grid(row=2, column=1, pady=5, padx=5, sticky="ew", columnspan=2)

    bulk_import_button = create_button(bulk_import_tab, text="Run Bulk Import", command=run_bulk_import_scrape_thread,
                                       primary=True)
    bulk_import_button.grid(row=3, column=0, pady=5, padx=5, sticky="ew", columnspan=3)

    # ! Poster Scrape Tab --
    poster_scrape_tab = tabview.add("Artwork Scrape")

    poster_scrape_tab.grid_columnconfigure(0, weight=0)
    poster_scrape_tab.grid_columnconfigure(1, weight=1)
    poster_scrape_tab.grid_columnconfigure(2, weight=0)

    poster_scrape_tab.grid_rowconfigure(0, weight=0)
    poster_scrape_tab.grid_rowconfigure(1, weight=0)
    poster_scrape_tab.grid_rowconfigure(2, weight=1)
    poster_scrape_tab.grid_rowconfigure(3, weight=0)

    url_label = ctk.CTkLabel(poster_scrape_tab,
                             text="Enter a ThePosterDB set URL, MediUX set URL, or ThePosterDB user URL",
                             text_color="#696969", font=("Roboto", 15))
    url_label.grid(row=0, column=0, columnspan=2, pady=5, padx=5, sticky="w")

    url_entry = ctk.CTkEntry(poster_scrape_tab, placeholder_text="e.g., https://mediux.pro/sets/6527",
                             fg_color="#1C1E1E", text_color="#A1A1A1", border_width=0, height=40)
    url_entry.grid(row=1, column=0, columnspan=2, pady=5, padx=5, sticky="ew")
    url_entry.bind("<Enter>", lambda event: on_hover_in(url_label))
    url_entry.bind("<Leave>", lambda event: on_hover_out(url_label))
    bind_context_menu(url_entry)

    clear_button = create_button(poster_scrape_tab, text="Clear", command=clear_url)
    clear_button.grid(row=3, column=0, pady=5, padx=5, ipadx=30, sticky="ew")

    scrape_button = create_button(poster_scrape_tab, text="Run URL Scrape", command=run_url_scrape_thread, primary=True)
    scrape_button.grid(row=3, column=1, pady=5, padx=5, sticky="ew", columnspan=2)

    poster_scrape_tab.grid_rowconfigure(2, weight=1)

    # ! Session Log Tab --
    session_log_tab = tabview.add("Session Log")
    session_log_tab.grid_columnconfigure(0, weight=0)
    session_log_tab.grid_columnconfigure(1, weight=3)
    session_log_tab.grid_columnconfigure(2, weight=0)

    # bulk_import_label = ctk.CTkLabel(bulk_import_tab, text=f"Bulk Import Text", text_color="#CECECE")
    # bulk_import_label.grid(row=0, column=0, pady=5, padx=10, sticky="w")
    session_log_text = ctk.CTkTextbox(
        session_log_tab,
        height=15,
        wrap="none",
        state="normal",
        fg_color="#1C1E1E",
        text_color="#A1A1A1",
        font=("Courier", 14)
    )
    session_log_text.configure(state="disabled")
    session_log_text.grid(row=1, column=0, padx=10, pady=5, sticky="nsew", columnspan=2)
    bind_context_menu(session_log_text)

    session_log_tab.grid_rowconfigure(0, weight=0)
    session_log_tab.grid_rowconfigure(1, weight=1)
    session_log_tab.grid_rowconfigure(2, weight=0)

    # Button row: Load, Save, Run buttons
    session_log_clear = create_button(session_log_tab, text="Clear Log", command=clear_log)
    session_log_clear.grid(row=2, column=0, pady=5, padx=5, sticky="ew", columnspan=3)


    # ! Status and Error Labels --
    status_label = ctk.CTkLabel(app, text="", text_color="#E5A00D")
    status_label.pack(side="bottom", fill="x", pady=(5))

    # ! Load configuration and bulk import data at start, set default tab
    load_and_update_ui()
    load_bulk_import_file()

    set_default_tab(
        tabview)  # default tab will be 'Settings' if base_url and token are not set, otherwise 'Bulk Import'

    app.mainloop()


# * CLI-based user input loop (fallback if no arguments were provided) ---
def interactive_cli_loop():

    global cli_options
    global config
    global plex
    global app

    while True:
        print("\n--- Poster Scraper Interactive CLI ---")
        print("1. Enter a ThePosterDB set URL, MediUX set URL, or ThePosterDB user URL.")
        print("2. Run Bulk Import from a file")
        print("3. Launch GUI")
        print("4. Exit")

        choice = input("Select an option (1-4): ")

        # Ask for the URL and then process it as appropriate
        if choice == '1':
            print("\nNote, this is a basic service only - if you want to use options such as additional posters, pass the URL and arguments in the command line.")
            url = input("Enter URL: ")
            if check_libraries():

                if "/user/" in url.lower():
                    try:
                        scrape_tpdb_user(url, cli_options)
                    except Exception as e:
                        print(str(e))
                else:
                    try:
                        scrape_and_upload(url, cli_options)
                    except Exception as e:
                        print(str(e))

        # Ask for a file and then run the bulk import
        elif choice == '2':
            file_path = input(f"Enter the path to the bulk import .txt file, or press [Enter] to use '{config.bulk_txt}': ")
            file_path = file_path.strip() if file_path else config.bulk_txt
            if check_libraries():
                parse_bulk_file_from_cli(file_path)

        elif choice == '3':
            print("Launching GUI...")

            # Create the app and UI
            app = ctk.CTk()
            create_ui()

            break  # Exit CLI loop to launch GUI

        elif choice == '4':
            print("Stopping...")
            break

        else:
            print("Invalid choice. Please select an option between 1 and 4.")


def check_libraries():

    global plex

    if not plex.tv_libraries:
        print("! No TV libraries initialized. Verify the 'tv_library' in config.json.")
    if not plex.movie_libraries:
        print("! No Movies libraries initialized. Verify the 'movie_library' in config.json.")
    return plex.tv_libraries and plex.movie_libraries


# Scrape all pages of a TPDb user's uploaded artwork
def scrape_tpdb_user(url, options):

    soup = soup_utils.cook_soup(url)
    pages = tpdb.scrape_user_info(soup)

    if not pages:
        print(f"x Could not determine the number of pages for {url}")
        return

    if "?" in url:
        cleaned_url = url.split("?")[0]
        url = cleaned_url

    for page in range(pages):
        # print(f"+ Scraping page {page + 1}.")
        page_url = f"{url}?section=uploads&page={page + 1}"

        # print (f"Scraping {page_url}")
        # a, b, c = scrape_single_url(page_url, options)
        # print(f"{len(a)} movie posters, {len(b)} show posters and {len(c)} collection posters on this page")

        scrape_and_upload(page_url, options)


# Scraped the URL then uploads what it's scraped to Plex
def scrape_and_upload(url, options):

    global plex

    # Let's scrape the posters first
    scraper = Scraper(url)
    scraper.set_options(options)
    scraper.scrape()

   # print(vars(scraper))

    # Now upload them to Plex
    processor = UploadProcessor(plex)
    processor.set_options(options)

    if scraper.collection_artwork:
        print("-----------------------------------------------------------------------------------")
        for artwork in scraper.collection_artwork:
            try:
                result = processor.process_collection_artwork(artwork)
                update_log(result)
            except CollectionNotFound as not_found:
                update_log(f"∙ {str(not_found)}")
            except NotProcessedByFilter as not_processed:
                update_log(f"- {str(not_processed)}")
            except Exception as error_unexpected:
                update_log(f"x {str(error_unexpected)}")

    if scraper.movie_artwork:
        if not scraper.collection_artwork:
            print("-----------------------------------------------------------------------------------")
        else:
            print("∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙∙")
        for artwork in scraper.movie_artwork:
            try:
                result = processor.process_movie_artwork(artwork)
                update_log(result)
            except MovieNotFound as not_found:
                update_log(f"∙ {str(not_found)}")
            except NotProcessedByFilter as not_processed:
                update_log(f"- {str(not_processed)}")
            except Exception as error_unexpected:
                update_log(f"x {str(error_unexpected)}")

    if scraper.tv_artwork:
        print("-----------------------------------------------------------------------------------")
        for artwork in scraper.tv_artwork:
            try:
                result = processor.process_tv_artwork(artwork)
                update_log(result)
            except ShowNotFound as not_found:
                update_log(f"∙ {str(not_found)}")
            except NotProcessedByFilter as not_processed:
                update_log(f"- {str(not_processed)}")
            except Exception as error_unexpected:
                update_log(f"x {str(error_unexpected)}")




# * Main Initialization ---
if __name__ == "__main__":

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

    # Create a connector for Plex
    plex = PlexConnector(config.base_url, config.token)

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

        # Create the GUI if we need to
        if cli_command == 'gui':

            # Erase any arguments set in the CLI
            cli_options = Options()

            # Create the UI now
            app = ctk.CTk()
            create_ui()

        # Handle the CLI options if we're not using the GUI
        elif cli_command == 'bulk':

            # Remove some of the command line options which should be specified per line
            cli_options.add_posters = False
            cli_options.add_sets = False
            cli_options.year = None
            cli_options.clear_filters()

            # Process using the bulk filename if supplied, else the bulk file set in the config
            parse_bulk_file_from_cli(args.bulk_file if args.bulk_file else config.bulk_txt)

        # Now we're looking at URLs - firstly one containing a TPDb user
        elif "/user/" in cli_command:

            # Remove some of the command line options which aren't applicable to user scraping
            cli_options.year = None
            cli_options.add_posters = False
            cli_options.add_sets = False
            scrape_tpdb_user(cli_command, cli_options)

        # User passed in a poster or set URL, so let's process that
        else:
            scrape_and_upload(cli_command, cli_options)

    else:

        # If no CLI arguments, proceed with UI creation (if not in interactive CLI mode)
        if not interactive_cli:

            # Connect to the TV and Movie libraries
            try:
                plex.set_tv_libraries(config.tv_library)
            except PlexConnectorException as e:
                sys.exit(str(e))

            try:
                plex.set_movie_libraries(config.movie_library)
            except PlexConnectorException as e:
                sys.exit(str(e))

            # Create the app and UI
            app = ctk.CTk()
            create_ui()



        else:

            sys.stdout.reconfigure(encoding='utf-8')
            gui_flag = cli_command == "gui"

            # Perform CLI plex_setup if GUI flag is not present
            if not gui_flag:

                # Connect to the TV and Movie libraries
                try:
                    plex.set_tv_libraries(config.tv_library)
                except PlexConnectorException as e:
                    sys.exit(str(e))

                try:
                    plex.set_movie_libraries(config.movie_library)
                except PlexConnectorException as e:
                    sys.exit(str(e))

            # Handle interactive CLI
            interactive_cli_loop()
