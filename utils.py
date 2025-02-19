import hashlib
import json
import re


# ---------------------- HELPER CLASSES ----------------------

# Command line or bulk file arguments, just a container to pass them around easily
class Options:
    def __init__(self, add_posters=False, add_sets=False, force=False):
        self.add_posters = add_posters
        self.add_sets = add_sets
        self.force = force

# A URL item stored with its options (force, add sets, add posters)
class URLItem:
    def __init__(self, url, options):

        """
        :rtype: object
        """

        self.url = url
        self.options = options


# Calculate the MD5 of a string - used for artwork IDs stored in labels
def calculate_md5(input_string):
    # Create an MD5 hash object
    md5_hash = hashlib.md5()

    # Update the hash object with the bytes of the input string
    md5_hash.update(input_string.encode('utf-8'))

    # Return the hexadecimal representation of the hash
    return md5_hash.hexdigest()




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

    """Check if the URL is not a comment or empty line."""

    regex = r"^(?!\/\/|#|^$)"
    pattern = re.compile(regex)
    return True if re.match(pattern, url) else False


# Parse a line from the bulk URL file, containing the URL and options
# @todo add validation for the URL
def parse_line(line):

    # Split the line by spaces
    parts = line.strip().split()

    # The first part should be the URL
    url = parts[0]

    # The rest are optional flags
    options = Options(
        add_posters='--add-posters' in parts,
        add_sets='--add-sets' in parts,
        force='--force' in parts
    )

    return URLItem(url, options)