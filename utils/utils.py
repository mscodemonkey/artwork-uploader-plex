import hashlib
import json
import re

import validators

from utils.notifications import debug_me
from models.options import Options
from models.url_item import URLItem
from pathlib import PureWindowsPath, PurePosixPath
from core.exceptions import InvalidUrl, InvalidFlag

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
        if parsed.netloc == "theposterdb.com":
            if "/set/" in url or "/poster/" in url or "/user/" in url:
                return True, ""
            return False, "Unsupported ThePosterDB URL type. Must contain /set/, /poster/, or /user/"

        elif parsed.netloc == "mediux.pro":
            if "/sets/" in url or "/boxsets/" in url:
                return True, ""
            return False, "Unsupported MediUX URL type. Must contain /sets/ or /boxsets/"

        elif url.endswith('.html'):
            return True, ""

        else:
            return False, f"Unsupported scraper source: {parsed.netloc}. Supported: theposterdb.com, mediux.pro"

    except Exception as e:
        return False, f"URL validation error: {str(e)}"


def parse_url_and_options(line):

    """
    Parse a line from the bulk URL file or the scrape URL in the GUI
    Each line could contain the URL and any options
    """

    debug_me(f"Line: {line}", "parse_url_and_options")

    year = None
    options = Options()

    # Split the line by flag delimiters (--) as in '--exclude s01 s02', '--filters title_card', '--year 2025' or simply '--temp'
    parts = line.strip().split(" --")

    # The first part should be a valid URL, raise exception otherwise
    url = parts[0].strip()
    if not validators.url(url):
        raise InvalidUrl(url)

    # Initiate list of invalid flags for logging purposes
    inv_flags=[]

    # Iterate through each flag provided
    for option in parts[1:]:
        # Split each option into its parts by spaces
        option_parts=option.strip().split(" ")
        # The option flag is the first one
        flag=option_parts[0].strip()
        # If it has more than one part, it's a flag with arguments (it should only be --filters, --exclude or --year)
        if len(option_parts)>1:
            # The flag arguments follow the flag
            args=option_parts[1:]
            if flag == "filters":
                # Set the filters
                options.filters = args
            elif flag == "exclude":
                # Set the exclusions
                options.exclude = args
            elif flag == "year":
                # The --year flag should only have one argument
                if len(args)>1:
                    inv_flags.append(f"--{flag} requires a single argument")
                    continue
                year_str = args[0]
                try:
                    year = int(year_str)
                except Exception:
                    year == None
                options.year = year
            # If it's one of these flags it shouldn't have any arguments
            elif flag in ["add-posters", "add-sets", "add-to-bulk", "force", "kometa", "stage", "temp"]:
                inv_flags.append(f"--{flag} has too many argumens")
            # If we ge to this point it's not a valid flag
            else:
                inv_flags.append(f"--{flag} is not a valid flag")
        # If it only has one part, it should be on of the boolean flags
        else:
            if flag in ["filters", "exclude", "year"]:
                inv_flags.append(f"--{flag} needs at least one argument")
            elif flag not in ["add-posters", "add-sets" ,"add-to-bulk" ,"force", "kometa", "stage", "temp"]:
                inv_flags.append(f"--{flag} is not a valid flag")
            else:
                setattr(options, flag.replace("-","_"), True) # Convert add-posters into add_posters as the Options class expects

    # If we've collected any invalid flash, raise exception and provide the list of invalid flags and reasons for logging purposes    
    if inv_flags:
        error = ", ".join(inv_flags)
        raise InvalidFlag(error)

    # If URL and all flags are valid, return URL and options
    return URLItem(url, options)

def is_valid_url(line):

    # Split the line by spaces - to handle a line with an url and options
    parts = line.strip().split()

    # The first part should be the URL
    url = parts[0]

    return validators.url(url) is True



def get_artwork_type(artwork):

    artwork_type = None
    filter_type = None

    if artwork["season"] == "Cover":
        artwork_type = "Show cover"
        filter_type = "show_cover"
    elif artwork["season"] == "Backdrop":
        artwork_type = "Background"
        filter_type = "background"
    elif artwork["season"] >= 0:
        if artwork["episode"] == "Cover":
            artwork_type = "Season cover"
            filter_type = "season_cover"
        elif artwork["episode"] is None:
            artwork_type = "Season cover"
            filter_type = "season_cover"
        elif artwork["episode"] >= 0:
            artwork_type = "Title card"
            filter_type = "title_card"

    return artwork_type, filter_type

def get_path_parts(path: str) -> list:
    if path is None:
        return None

    is_windows_drive = re.match(r"^[A-Za-z]:\\", path) is not None
    is_unc = path.startswith("\\\\")
    has_backslashes_only = "\\" in path and "/" not in path

    if is_windows_drive or is_unc or has_backslashes_only:
        return PureWindowsPath(path).parts
    else:
        return PurePosixPath(path).parts

def get_host_path(container_path: str) -> str:
    """
    Parses /proc/self/mountinfo to find the host path
    corresponding to the given container path.
    """
    try:
        with open("/proc/self/mountinfo", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 5:
                    continue
                target = parts[4].strip()
                if container_path == target:
                    host_path = parts[3]
                    if "path=" in line:
                        drive=line.split("path=")[1].split(";")[0].rstrip('\\')
                        full_path = f"{drive}{host_path}".replace("/", "\\")
                        return full_path
                    return host_path
    except Exception as e:
        debug_me(f"Error reading /proc/self/mountinfo: {e}", "get_host_path")
    return "(not defined)"

