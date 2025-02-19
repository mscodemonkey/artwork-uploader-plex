import time
import utils



def find_existing_artwork(target_item, artwork_type, poster):

    existing_artwork = False

    artwork_id = artwork_type[:1].upper() + "ID:"  # This will be BID, CID, EID, PID, SID for backgrounds, covers, episode cards, posters or season covers
    new_label = artwork_id + utils.calculate_md5(poster["url"])

    # print(f"Looking for {new_label}")

    for label in target_item.labels:

        existing_label = str(label)  # Convert the label object to a string if it's not already

        if existing_label.startswith(artwork_id):

            if existing_label == new_label:
                existing_artwork = True
            else:
                target_item.removeLabel(existing_label, False)  # Remove the label as we're replacing the artwork

    return existing_artwork, new_label


def find_in_library(library, poster):
    items = []

    # print(f"Searching for item in Plex {poster}")

    for lib in library:
        try:
            if poster["year"] is not None:
                library_item = lib.get(poster["title"], year=poster["year"])
            else:
                library_item = lib.get(poster["title"])

            if library_item:
                items.append(library_item)
        except:
            pass

    if items:
        # print(f"Found {items}")
        return items

    # print(f"x {poster['title']} not found, skipping.")
    return None


def find_collection(library, poster):
    collections = []
    for lib in library:
        try:
            movie_collections = lib.collections()
            for plex_collection in movie_collections:
                if plex_collection.title == poster["title"]:
                    collections.append(plex_collection)
        except:
            pass

    if collections:
        return collections

    # print(f"{poster['title']} not found, skipping.")
    return None
