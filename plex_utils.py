


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
