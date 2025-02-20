import requests
import os
import json
import sys
from plexapi.server import PlexServer
import plexapi.exceptions
import customtkinter as ctk
import tkinter as tk
import threading
import xml.etree.ElementTree
import atexit
import sys
from PIL import Image

import plex_connector_exception
import arguments
import upload_processor
from upload_processor import UploadProcessor
from scraper import Scraper
import soup_utils
import tpdb
import utils
from options import Options
from plex_connector import PlexConnector
from upload_processor_exceptions import CollectionNotFound, MovieNotFound, ShowNotFound

# ! Interactive CLI mode flag
interactive_cli = True  # Set to False when building the executable with PyInstaller for it launches the GUI by default


# @ ---------------------- CORE FUNCTIONS ----------------------

def plex_setup(gui_mode=False, gui=None):
    global plexServer
    plexServer = None

    # Check if config.json exists
    if os.path.exists("config.json"):
        try:
            config = json.load(open("config.json"))
            base_url = config.get("base_url", "")
            token = config.get("token", "")
            tv_library = config.get("tv_library", [])
            movie_library = config.get("movie_library", [])
        except Exception as e:
            if gui_mode:
                app.after(300, update_error, f"Error with config.json: {str(e)}")
            else:
                sys.exit("Error with config.json file. Please consult the readme.md.")
            return None, None
    else:
        # No config file, skip setting up Plex for now
        base_url, token, tv_library, movie_library = "", "", [], []

    # Validate the fields
    if not base_url or not token:
        if gui_mode:
            app.after(100, update_error,
                      "Invalid Plex token or base URL. Please provide valid values in config.json or via the GUI.")
        else:
            print('Invalid Plex token or base URL. Please provide valid values in config.json or via the GUI.')
        return None, None

    try:
        plexServer = PlexServer(base_url, token)  # Initialize the Plex server connection
    except requests.exceptions.RequestException as e:
        # Handle network-related errors (e.g., unable to reach the server)
        if gui_mode:
            app.after(100, update_error, f"Unable to connect to Plex server: {str(e)}")
        else:
            sys.exit('Unable to connect to Plex server. Please check the "base_url" in config.json or provide one.')
        return None, None
    except plexapi.exceptions.Unauthorized as e:
        # Handle authentication-related errors (e.g., invalid token)
        if gui_mode:
            app.after(100, update_error, f"Invalid Plex token: {str(e)}")
        else:
            sys.exit('Invalid Plex token. Please check the "token" in config.json or provide one.')
        return None, None
    except xml.etree.ElementTree.ParseError as e:
        # Handle XML parsing errors (e.g., invalid XML response from Plex)
        if gui_mode:
            app.after(100, update_error, f"Received invalid XML from Plex server: {str(e)}")
        else:
            print("Received invalid XML from Plex server. Check server connection.")
        return None, None
    except Exception as e:
        # Handle any other unexpected errors
        if gui_mode:
            app.after(100, update_error, f"Unexpected error: {str(e)}")
        else:
            sys.exit(f"Unexpected error: {str(e)}")
        return None, None

    # Continue with the setup (assuming plex server is successfully initialized)
    if isinstance(tv_library, str):
        tv_library = [tv_library]
    elif not isinstance(tv_library, list):
        if gui_mode:
            app.after(100, update_error, "tv_library must be either a string or a list")
        sys.exit("tv_library must be either a string or a list")

    tv = []
    for tv_lib in tv_library:
        try:
            plex_tv = plexServer.library.section(tv_lib)
            tv.append(plex_tv)
        except plexapi.exceptions.NotFound as e:
            if gui_mode:
                app.after(100, update_error, f'TV library named "{tv_lib}" not found: {str(e)}')
            else:
                sys.exit(
                    f'TV library named "{tv_lib}" not found. Please check the "tv_library" in config.json or provide one.')

    if isinstance(movie_library, str):
        movie_library = [movie_library]
    elif not isinstance(movie_library, list):
        if gui_mode:
            app.after(100, update_error, "movie_library must be either a string or a list")
        sys.exit("movie_library must be either a string or a list")

    movies = []
    for movie_lib in movie_library:
        try:
            plex_movie = plexServer.library.section(movie_lib)
            movies.append(plex_movie)
        except plexapi.exceptions.NotFound as e:
            if gui_mode:
                app.after(100, update_error, f'Movie library named "{movie_lib}" not found: {str(e)}')
            else:
                sys.exit(
                    f'Movie library named "{movie_lib}" not found. Please check the "movie_library" in config.json or provide one.')

    return tv, movies



def parse_bulk_import_file(bulk_import_list):

    """ Parse the URLs from a bulk import list and scrape them """

    valid_urls = []

    # Loop through the import file and build a list of URLs and options
    # Ignoring any lines containing comments using # or //

    for line in bulk_import_list:
        if utils.is_not_comment(line):
            url_item_details = utils.parse_line(line)
            valid_urls.append(url_item_details)

    for valid_url in valid_urls:

        # If it's a ThePosterDB user then scrape the URL
        # @todo Pass the line options to this function too
        # @todo Check the logic for the else, doesn't really make sense to return the whole list here, surely it should scrape the URL for posters?
        if "/user/" in valid_url.url:
            print(f"Scraping user data from: {valid_url.url}")
            scrape_tpdb_user(valid_url.url, valid_url.options)
        else:
            print(f"Returning non-user URL: {valid_url.url}")
            # If it's not a /user/ URL (should theoretically be a poster set), return it
            return valid_urls

    return valid_urls


def parse_cli_urls(plex, file_path, tv, movies):

    """Parse the URLs from a file and scrape them."""

    try:

        with open(file_path, 'r', encoding='utf-8') as file:
            urls = file.readlines()

        for line in urls:

            if utils.is_not_comment(line):

                url_details = utils.parse_line(line)

                if "/user/" in url_details.url:
                    scrape_tpdb_user(url_details.url, url_details.options)
                else:
                    scrape_and_upload(url_details.url, url_details.options)

    except FileNotFoundError:
        print("File not found. Please enter a valid file path.")


def cleanup():
    '''Function to handle cleanup tasks on exit.'''
    if plex:
        print("Closing Plex server connection...")
    print("Exiting application. Cleanup complete.")


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
    '''Helper function to get the absolute path based on the script's location.'''
    print("relative_path", relative_path)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, relative_path)


def update_status(message, color="white"):
    '''Update the status label with a message and color.'''
    app.after(0, lambda: status_label.configure(text=message, text_color=color))


def update_error(message):
    '''Update the error label with a message, with a small delay.'''
    # app.after(500, lambda: status_label.configure(text=message, text_color="red"))
    status_label.configure(text=message, text_color="red")


def clear_url():
    '''Clear the URL entry field.'''
    url_entry.delete(0, ctk.END)
    status_label.configure(text="URL cleared.", text_color="orange")


def set_default_tab(tabview):
    '''Set the default tab to the Settings tab.'''
    plex_base_url = base_url_entry.get()
    plex_token = token_entry.get()

    if plex_base_url and plex_token:
        tabview.set("Bulk Import")
    else:
        tabview.set("Settings")


def bind_context_menu(widget):
    '''Bind the right-click context menu to the widget.'''
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
    '''Show the global context menu at the cursor position.'''
    widget = event.widget
    global_context_menu.entryconfigure("Cut", command=lambda: widget.event_generate("<<Cut>>"))
    global_context_menu.entryconfigure("Copy", command=lambda: widget.event_generate("<<Copy>>"))
    global_context_menu.entryconfigure("Paste", command=lambda: widget.event_generate("<<Paste>>"))
    global_context_menu.tk_popup(event.x_root, event.y_root)


# * Configuration file I/O functions  ---

def load_config(config_path="config.json"):
    '''Load the configuration from the JSON file. If it doesn't exist, create it with default values.'''
    default_config = {
        "base_url": "",
        "token": "",
        "bulk_txt": "bulk_import.txt",
        "tv_library": ["TV Shows", "Anime"],
        "movie_library": ["Movies"],
        "mediux_filters": ["title_card", "background", "season_cover", "show_cover"]
    }

    # Create the config.json file if it doesn't exist
    if not os.path.isfile(config_path):
        try:
            with open(config_path, "w") as config_file:
                json.dump(default_config, config_file, indent=4)
            print(f"Config file '{config_path}' created with default settings.")
        except Exception as e:
            update_error(f"Error creating config: {str(e)}")
            return {}

    # Load the configuration from the config.json file
    try:
        with open(config_path, "r") as config_file:
            config = json.load(config_file)

        base_url = config.get("base_url", "")
        token = config.get("token", "")
        tv_library = config.get("tv_library", [])
        movie_library = config.get("movie_library", [])
        mediux_filters = config.get("mediux_filters", [])
        bulk_txt = config.get("bulk_txt", "bulk_import.txt")

        return {
            "base_url": base_url,
            "token": token,
            "tv_library": tv_library,
            "movie_library": movie_library,
            "mediux_filters": mediux_filters,
            "bulk_txt": bulk_txt
        }
    except Exception as e:
        update_error(f"Error loading config: {str(e)}")
        return {}


def save_config():
    '''Save the configuration from the UI fields to the file and update the in-memory config.'''

    new_config = {
        "base_url": base_url_entry.get().strip(),
        "token": token_entry.get().strip(),
        "tv_library": [item.strip() for item in tv_library_text.get().strip().split(",")],
        "movie_library": [item.strip() for item in movie_library_text.get().strip().split(",")],
        "mediux_filters": mediux_filters_text.get().strip().split(", "),
        "bulk_txt": bulk_txt_entry.get().strip()
    }

    try:
        with open("config.json", "w") as f:
            json.dump(new_config, f, indent=4)

        # Update the in-memory config dictionary
        global config
        config = new_config

        load_and_update_ui()

        update_status("Configuration saved successfully!", color="#E5A00D")
    except Exception as e:
        update_status(f"Error saving config: {str(e)}", color="red")


def load_and_update_ui():
    '''Load the configuration and update the UI fields.'''
    config = load_config()

    if base_url_entry is not None:
        base_url_entry.delete(0, ctk.END)
        base_url_entry.insert(0, config.get("base_url", ""))

    if token_entry is not None:
        token_entry.delete(0, ctk.END)
        token_entry.insert(0, config.get("token", ""))

    if bulk_txt_entry is not None:
        bulk_txt_entry.delete(0, ctk.END)
        bulk_txt_entry.insert(0, config.get("bulk_txt", "bulk_import.txt"))

    if tv_library_text is not None:
        tv_library_text.delete(0, ctk.END)
        tv_library_text.insert(0, ", ".join(config.get("tv_library", [])))

    if movie_library_text is not None:
        movie_library_text.delete(0, ctk.END)
        movie_library_text.insert(0, ", ".join(config.get("movie_library", [])))

    if mediux_filters_text is not None:
        mediux_filters_text.delete(0, ctk.END)
        mediux_filters_text.insert(0, ", ".join(config.get("mediux_filters", [])))

    load_bulk_import_file()


# * Threaded functions for scraping and setting posters ---

def run_url_scrape_thread():
    '''Run the URL scrape in a separate thread.'''
    global scrape_button, clear_button, bulk_import_button
    url = url_entry.get()

    if not url:
        update_status("Please enter a valid URL.", color="red")
        return

    scrape_button.configure(state="disabled")
    clear_button.configure(state="disabled")
    bulk_import_button.configure(state="disabled")

    threading.Thread(target=process_scrape_url, args=(url,)).start()


def run_bulk_import_scrape_thread():
    '''Run the bulk import scrape in a separate thread.'''
    global bulk_import_button
    bulk_import_list = bulk_import_text.get(1.0, ctk.END).strip().split("\n")
    valid_urls = parse_bulk_import_file(bulk_import_list)

    if not valid_urls:
        app.after(0, lambda: update_status("No bulk import entries found.", color="red"))
        return

    scrape_button.configure(state="disabled")
    clear_button.configure(state="disabled")
    bulk_import_button.configure(state="disabled")

    threading.Thread(target=process_bulk_import, args=(valid_urls,)).start()


# * Processing functions for scraping and setting posters ---

def process_scrape_url(url):
    '''Process the URL scrape.'''
    try:
        # Perform plex setup
        tv, movies = plex_setup(gui_mode=True)

        # Check if plex setup returned valid values
        if tv is None or movies is None:
            update_status("Plex setup incomplete. Please configure your settings.", color="red")
            return

        soup = soup_utils.cook_soup(url)
        update_status(f"Scraping: {url}", color="#E5A00D")

        url_with_options = utils.parse_line(url)

        # Proceed with setting posters
        scrape_and_upload(url_with_options.url, url_with_options.options)
        update_status(f"Posters successfully set for: {url}", color="#E5A00D")

    except Exception as e:
        update_status(f"Error: {e}", color="red")

    finally:
        app.after(0, lambda: [
            scrape_button.configure(state="normal"),
            clear_button.configure(state="normal"),
            bulk_import_button.configure(state="normal"),
        ])


def process_bulk_import(plex, valid_urls):
    '''Process the bulk import scrape.'''
    try:
        tv, movies = plex_setup(gui_mode=True)

        # Check if plex setup returned valid values
        if tv is None or movies is None:
            update_status("Plex setup incomplete. Please configure your settings.", color="red")
            return

        for i, valid_url in enumerate(valid_urls):
            status_text = f"Processing item {i + 1} of {len(valid_urls)}: {valid_url.url}"
            update_status(status_text, color="#E5A00D")
            scrape_and_upload(valid_url.url, valid_url.options)
            update_status(f"Completed: {valid_url.url}", color="#E5A00D")

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
    '''Load the bulk import file into the text area.'''
    try:
        # Get the current bulk_txt value from the config
        bulk_txt_path = config.get("bulk_txt", "bulk_import.txt")

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
    '''Save the bulk import text area content to a file relative to the executable location.'''
    try:
        exe_path = get_exe_dir()
        bulk_txt_path = os.path.join(exe_path, config.get("bulk_txt", "bulk_import.txt"))

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
    '''Create the main UI window.'''
    global plex, app, global_context_menu, scrape_button, clear_button, mediux_filters_text, bulk_import_text, base_url_entry, token_entry, status_label, url_entry, app, bulk_import_button, tv_library_text, movie_library_text, bulk_txt_entry

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
        '''Open a URL in the default web browser.'''
        import webbrowser
        webbrowser.open(url)

    # ! Create a frame for the link bar --
    link_bar = ctk.CTkFrame(app, fg_color="transparent")
    link_bar.pack(fill="x", pady=5, padx=10)

    # ? Link to Plex Media Server from the base URL
    base_url = config.get("base_url", None)
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
    tabview.pack(fill="both", expand=True, padx=10, pady=0)

    tabview.configure(
        fg_color="#2A2B2B",
        segmented_button_fg_color="#1C1E1E",
        segmented_button_selected_color="#2A2B2B",
        segmented_button_selected_hover_color="#2A2B2B",
        segmented_button_unselected_color="#1C1E1E",
        segmented_button_unselected_hover_color="#1C1E1E",
        text_color="#CECECE",
        text_color_disabled="#777777",
        border_color="#484848",
        border_width=1,
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
    mediux_filters_label = ctk.CTkLabel(settings_tab, text="Mediux Filters", text_color="#696969", font=("Roboto", 15))
    mediux_filters_label.grid(row=5, column=0, pady=5, padx=10, sticky="w")
    mediux_filters_text = ctk.CTkEntry(settings_tab, fg_color="#1C1E1E", text_color="#A1A1A1", border_width=0,
                                       height=40)
    mediux_filters_text.grid(row=5, column=1, pady=5, padx=10, sticky="ew")
    mediux_filters_text.bind("<Enter>", lambda event: on_hover_in(mediux_filters_label))
    mediux_filters_text.bind("<Leave>", lambda event: on_hover_out(mediux_filters_label))
    bind_context_menu(mediux_filters_text)

    settings_tab.grid_rowconfigure(0, weight=0)
    settings_tab.grid_rowconfigure(1, weight=0)
    settings_tab.grid_rowconfigure(2, weight=0)
    settings_tab.grid_rowconfigure(3, weight=0)
    settings_tab.grid_rowconfigure(4, weight=0)
    settings_tab.grid_rowconfigure(5, weight=0)
    settings_tab.grid_rowconfigure(6, weight=1)

    # ? Load and Save Buttons (Anchored to the bottom)
    load_button = create_button(settings_tab, text="Reload", command=load_and_update_ui)
    load_button.grid(row=7, column=0, pady=5, padx=5, ipadx=30, sticky="ew")
    save_button = create_button(settings_tab, text="Save", command=save_config, primary=True)
    save_button.grid(row=7, column=1, pady=5, padx=5, sticky="ew")

    settings_tab.grid_rowconfigure(7, weight=0, minsize=40)

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
    poster_scrape_tab = tabview.add("Poster Scrape")

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
def interactive_cli_loop(plex, tv, movies, bulk_txt):
    while True:
        print("\n--- Poster Scraper Interactive CLI ---")
        print("1. Enter a ThePosterDB set URL, MediUX set URL, or ThePosterDB user URL")
        print("2. Run Bulk Import from a file")
        print("3. Launch GUI")
        print("4. Stop")

        choice = input("Select an option (1-4): ")

        if choice == '1':
            url = input("Enter the URL: ")
            if check_libraries(tv, movies):

                options = url_args

                if "/user/" in url.lower():
                    scrape_tpdb_user(url, options)
                else:
                    scrape_and_upload(url, options)

        elif choice == '2':
            file_path = input(f"Enter the path to the bulk import .txt file, or press [Enter] to use '{bulk_txt}': ")
            file_path = file_path.strip() or bulk_txt
            if check_libraries(tv, movies):
                parse_cli_urls(plex, file_path, tv, movies)

        elif choice == '3':
            print("Launching GUI...")
            tv, movies = plex_setup(gui_mode=True)
            create_ui()
            break  # Exit CLI loop to launch GUI

        elif choice == '4':
            print("Stopping...")
            break

        else:
            print("Invalid choice. Please select an option between 1 and 4.")


def check_libraries(tv, movies):
    if not tv:
        print("No TV libraries initialized. Verify the 'tv_library' in config.json.")
    if not movies:
        print("No Movies libraries initialized. Verify the 'movie_library' in config.json.")
    return bool(tv) and bool(movies)


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

    # Let's scrape the posters first
    scraper = Scraper(url)
    scraper.set_options(options)
    scraper.scrape()

    # Now upload them to Plex
    processor = UploadProcessor(plex)
    processor.set_options(options)

    for artwork in scraper.collection_artwork:
        try:
            processor.process_collection_artwork(artwork)
        except CollectionNotFound as error_not_found:
            print(f"∙ {str(error_not_found)}")
        except Exception as error_unexpected:
            print(f"x Unexpected exception occurred: {str(error_unexpected)}")

    for artwork in scraper.movie_artwork:
        try:
            processor.process_movie_artwork(artwork)
        except MovieNotFound as error_not_found:
            print(f"∙ {str(error_not_found)}")
        except Exception as error_unexpected:
            print(f"x Unexpected exception occurred: {str(error_unexpected)}")

    for artwork in scraper.tv_artwork:
        try:
            processor.process_tv_artwork(artwork)
        except ShowNotFound as error_not_found:
            print(f"∙ {str(error_not_found)}")
        except Exception as error_unexpected:
            print(f"x Unexpected exception occurred: {str(error_unexpected)}")





# * Main Initialization ---
if __name__ == "__main__":

    PlexServer = None # temp to remove later once we've got rid of plex_setup

    args = arguments.parse_arguments()  # Command line arguments

    url_args = Options(add_posters=args.add_posters, add_sets=args.add_sets,
                       force=args.force)  # Arguments per url to process

    config = load_config()
    bulk_txt = config.get("bulk_txt", "bulk_import.txt")

    plex = PlexConnector(config.get("base_url"), config.get("token"))

    app = None
    tv = None
    movies = None

    # Check for CLI arguments regardless of interactive_cli flag
    if len(sys.argv) > 1:

        command = args.command

        # Connect to the TV and Movie libraries
        try:
            plex.set_tv_libraries(config.get("tv_library"))
        except plex_connector_exception.PlexConnectorException as e:
            sys.exit(str(e))

        try:
            plex.set_movie_libraries(config.get("movie_library"))
        except plex_connector_exception.PlexConnectorException as e:
            sys.exit(str(e))

        # Create the GUI if we need to
        if command == 'gui':
            app = ctk.CTk()
            create_ui()

        # Handle the CLI options if we're not using the GUI
        elif command == 'bulk' and tv and movies:
            if args.bulk_file:
                file_path = args.bulk_file
                parse_cli_urls(file_path, plex.tv_libraries, plex.movie_libraries)
            else:
                print(f"Using bulk import file: {bulk_txt}")
                parse_cli_urls(bulk_txt, plex.tv_libraries, plex.movie_libraries)

        elif "/user/" in command:
            scrape_tpdb_user(command, url_args)
        else:
            scrape_and_upload(command, url_args)

    else:
        # If no CLI arguments, proceed with UI creation (if not in interactive CLI mode)
        if not interactive_cli:

            # Create the app and UI
            app = ctk.CTk()
            create_ui()

            # Connect to the TV and Movie libraries
            try:
                plex.set_tv_libraries(config.get("tv_library"))
            except plex_connector_exception.PlexConnectorException as e:
                app.after(100, update_error, e.gui_message)

            try:
                plex.set_movie_libraries(config.get("movie_library"))
            except plex_connector_exception.PlexConnectorException as e:
                app.after(100, update_error, e.gui_message)

        else:
            sys.stdout.reconfigure(encoding='utf-8')
            gui_flag = (len(sys.argv) > 1 and sys.argv[1].lower() == 'gui')

            # Perform CLI plex_setup if GUI flag is not present
            if not gui_flag:

                # Connect to the TV and Movie libraries
                try:
                    plex.set_tv_libraries(config.get("tv_library"))
                except plex_connector_exception.PlexConnectorException as e:
                    sys.exit(str(e))

                try:
                    plex.set_movie_libraries(config.get("movie_library"))
                except plex_connector_exception.PlexConnectorException as e:
                    sys.exit(str(e))


            # Handle interactive CLI
            interactive_cli_loop(plex, plex.tv_libraries, plex.movie_libraries, bulk_txt)
