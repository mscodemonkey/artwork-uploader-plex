import hashlib
import json
import re
from pathlib import PureWindowsPath, PurePosixPath

import validators
from core.constants import (
    TPDB_BASE_URL, MEDIUX_BASE_URL,
    SEASON_COVER, SEASON_BACKDROP, EPISODE_COVER,
    FILTER_SHOW_COVER, FILTER_BACKGROUND, FILTER_SEASON_COVER, FILTER_TITLE_CARD
)
from models.options import Options
from models.url_item import URLItem
from utils.notifications import debug_me


# ---------------------- HELPER CLASSES ----------------------


# Calculate the MD5 of a string - used for artwork IDs stored in labels
def calculate_md5(input_string):
    # Create an MD5 hash object
    md5_hash = hashlib.md5()

    # Update the hash object with the bytes of the input string
    md5_hash.update(input_string.encode('utf-8'))

    # Return the hexadecimal representation of the hash
    return md5_hash.hexdigest()


def calculate_file_md5(file_path):
    md5_hash = hashlib.md5()

    with open(file_path, "rb") as file:
        # Read the file in chunks to handle large files
        while chunk := file.read(8192):  # 8 KB chunks
            md5_hash.update(chunk)

    return md5_hash.hexdigest()


def is_numeric(value):
    if isinstance(value, (int, float)):  # Directly check if it's a number
        return True
    if isinstance(value, str) and value.isnumeric():  # Check if string is numeric
        return True
    return False  # Return False for None, non-numeric strings, or other types


def title_cleaner(string):
    if " (" in string:
        title = string.split(" (")[0]
    elif " -" in string:
        title = string.split(" -")[0]
    else:
        title = string

    title = title.strip()

    return title


def parse_string_to_dict(input_string):
    # Remove unnecessary replacements
    input_string = input_string.replace('\\\\\\\"', "")
    input_string = input_string.replace("\\", "")
    input_string = input_string.replace("u0026", "&")

    # Find JSON data in the input string
    json_start_index = input_string.find('{')
    json_end_index = input_string.rfind('}')
    json_data = input_string[json_start_index:json_end_index + 1]

    # Parse JSON data into a dictionary
    parsed_dict = json.loads(json_data)
    return parsed_dict


def remove_duplicates(lst):
    # Create an empty list to store unique elements
    unique = []
    # Create a set to track already seen elements
    seen = set()

    for item in lst:
        # Convert dictionaries to a tuple of items for comparison
        item_tuple = tuple(item.items()) if isinstance(item, dict) else item
        # Only add to unique list if it has not been seen before
        if item_tuple not in seen:
            seen.add(item_tuple)
            unique.append(item)

    return unique


# Check if the URL is not a comment or empty line.
def is_not_comment(url):
    """
    Check if the URL is not a comment or empty line.
    """

    regex = r"^(?!\/\/|#|^$)"
    pattern = re.compile(regex)
    return True if re.match(pattern, url) else False


def validate_scraper_url(url: str) -> tuple:
    """
    Validate that URL is from a supported scraper source.

    Args:
        url: URL to validate

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty string.

    Example:
        >>> is_valid, error = validate_scraper_url("https://theposterdb.com/set/123")
        >>> if not is_valid:
        ...     print(f"Invalid URL: {error}")
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)

        # Check basic URL structure
        if not parsed.scheme or not parsed.netloc:
            return False, f"Invalid URL format: {url}"

        # Check for supported sources
        if parsed.netloc == urlparse(TPDB_BASE_URL).hostname:
            if "/set/" in url or "/poster/" in url or "/user/" in url:
                return True, ""
            return False, "Unsupported ThePosterDB URL type. Must contain /set/, /poster/, or /user/"

        elif parsed.netloc == urlparse(MEDIUX_BASE_URL).hostname:
            if "/sets/" in url or "/boxsets/" in url:
                return True, ""
            return False, "Unsupported MediUX URL type. Must contain /sets/ or /boxsets/"

        elif url.endswith('.html'):
            return True, ""

        else:
            tpdb_host = urlparse(TPDB_BASE_URL).hostname
            mediux_host = urlparse(MEDIUX_BASE_URL).hostname
            return False, f"Unsupported scraper source: {parsed.netloc}. Supported: {tpdb_host}, {mediux_host}"

    except Exception as e:
        return False, f"URL validation error: {str(e)}"


def parse_url_and_options(line):
    """
    Parse a line from the bulk URL file or the scrape URL in the GUI
    Each line could contain the URL and any options
    """

    debug_me(f"Line: {line}")

    # Split the line by spaces
    parts = line.strip().split()

    # The first part should be the URL
    url = parts[0]

    # Initialise filters list or None
    exclude = None
    filters = None
    year = None

    # Process optional flags
    if '--filters' in parts:
        index = parts.index('--filters') + 1
        if index < len(parts) and not parts[index].startswith('--'):
            filters = []
            while index < len(parts) and not parts[index].startswith('--'):
                filters.append(parts[index])
                index += 1

    if '--exclude' in parts:
        index = parts.index('--exclude') + 1
        if index < len(parts) and not parts[index].startswith('--'):
            exclude = []
            while index < len(parts) and not parts[index].startswith('--'):
                exclude.append(parts[index])
                index += 1

    if '--year' in parts:
        index = parts.index('--year') + 1
        if index < len(parts) and not parts[index].startswith('--'):
            year_str = ""
            while index < len(parts) and not parts[index].startswith('--'):
                year_str = year_str + parts[index]
                index += 1
            # Convert to integer if we got a value, otherwise leave as None
            if year_str:
                try:
                    year = int(year_str)
                except ValueError:
                    # If conversion fails, leave as None
                    debug_me(f"Invalid year value: {year_str}, ignoring")
                    year = None

    options = Options(
        add_posters='--add-posters' in parts,
        add_sets='--add-sets' in parts,
        add_to_bulk='--add-to-bulk' in parts,
        force='--force' in parts,
        kometa='--kometa' in parts,
        stage='--stage' in parts,
        temp='--temp' in parts,
        filters=filters,  # Store the list of filters or None
        exclude=exclude,
        year=year  # Store the year as int or None
    )

    return URLItem(url, options)


def is_valid_url(line):
    # Split the line by spaces - to handle a line with a url and options
    parts = line.strip().split()

    # The first part should be the URL
    url = parts[0]

    return validators.url(url) is True


def get_artwork_type(artwork):
    artwork_type = None
    filter_type = None

    if artwork["season"] == SEASON_COVER:
        artwork_type = "Show cover"
        filter_type = FILTER_SHOW_COVER
    elif artwork["season"] == SEASON_BACKDROP:
        artwork_type = "Background"
        filter_type = FILTER_BACKGROUND
    elif artwork["season"] >= 0:
        if artwork["episode"] == EPISODE_COVER:
            artwork_type = "Season cover"
            filter_type = FILTER_SEASON_COVER
        elif artwork["episode"] is None:
            artwork_type = "Season cover"
            filter_type = FILTER_SEASON_COVER
        elif artwork["episode"] >= 0:
            artwork_type = "Title card"
            filter_type = FILTER_TITLE_CARD

    return artwork_type, filter_type


def get_path_parts(path: str) -> tuple[str, ...] | None:
    if path is None:
        return None

    is_windows_drive = re.match(r"^[A-Za-z]:\\", path) is not None
    is_unc = path.startswith("\\\\")
    has_backslashes_only = "\\" in path and "/" not in path

    if is_windows_drive or is_unc or has_backslashes_only:
        return PureWindowsPath(path).parts
    else:
        return PurePosixPath(path).parts
