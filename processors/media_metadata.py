import re

from utils.notifications import debug_me


def parse_show(media_title):
    title = media_title.split(" (")[0]
    year = None
    season = "Cover"

    try:
        year = int(media_title.split(" (")[1].split(")")[0])
    except (IndexError, ValueError):
        pass

    if " - " in media_title:
        split_season = media_title.split(" - ")[-1]
        if split_season == "Specials":
            season = 0
        elif "Season" in split_season:
            season = int(split_season.split(" ")[1])

    return title, season, year



# Rewrote to use a regex because it was not working for one movie with actual brackets in the title
# Birdman (or The Unexpected Virtue of Ignorance) (2014)

def parse_movie(movie_title):

    try:
        match = re.match(r'^(.*?)(?:\s*\((\d{4})\))?$', movie_title.strip())
        if match:
            title = match.group(1).strip()
            year = int(match.group(2)) if match.group(2) else None
            return title, year
    except (AttributeError, ValueError, TypeError) as e:
        debug_me(f"Couldn't match {movie_title}", "parse_movie")
        return None, None


import re

def parse_title(title: str):
    # Strip any trailing spaces before the extension
    title = re.sub(r"\s+\.", ".", title).strip()

    # Regular expression patterns to match TV shows, movies, collections, episodes, and backgrounds
    episode_pattern = r".*S(?P<season>\d+)\sE(?P<episode>\d+).*"
    season_pattern = r".*Season\s(?P<season>\d+).*"
    specials_pattern = r".*- Specials.*"
    title_pattern_with_year = r"^(?P<title>.+)\s\((?P<year>\d{4})\)$"
    title_pattern_without_year = r"^(?P<title>.+)$"

    movie_or_show_pattern = r"^(?P<title>.+)\s\((?P<year>\d{4})\)"
    background_pattern = r"^(?P<title>.+)\s\((?P<year>\d{4})\)\s-\sBackdrop"
    collection_pattern = r"^(?!.*\(\d{4}\))(?P<title>.+)$" # Collections don't have a year in their name and some collection poster files don't have the word "Collection" in them

    # If it matches the episode pattern (SxxExx), it's a TV show title card
    # We populate the season, episode and set artwork type to title_card, and then extract the base title for further processing
    episode_match = re.match(episode_pattern, title, re.IGNORECASE)
    if episode_match:
        season = int(episode_match.group('season'))
        episode = int(episode_match.group('episode'))
        type = "title_card"
        base = re.split(r"\s-\sS\d+\s*E\d+.*", title, 1)[0].strip()

    # If it matches the season pattern, it's a TV show season cover
    # We populate the season, set episode to None and artwork type to season_cover, and then extract the base title for further processing
    season_match = re.match(season_pattern, title, re.IGNORECASE)
    if season_match:
        season = int(season_match.group('season'))
        episode = None
        type = "season_cover"
        base = re.split(r"\s-\sSeason\s\d+.*", title, 1)[0].strip()
    
    # If it matches the specials pattern, it's a TV show specials season cover
    # We set season to 0, episode to None, and artwork type to season_cover, and then extract the base title for further processing
    specials_match = re.match(specials_pattern, title, re.IGNORECASE)
    if specials_match:
        season = 0
        episode = None
        type = "season_cover"
        base = re.split(r"\s-\sSpecials.*", title, 1)[0].strip()

    # If any of the above matched, we process as a TV show
    if episode_match or season_match or specials_match:
        # We check if the title includes a year in parentheses
        title_match = re.match(title_pattern_with_year, base)
        if not title_match:
            # Try matching without year
            title_match = re.match(title_pattern_without_year, base)
            if title_match:
                # We extract the title, set year to None
                title_only = title_match.group('title').strip()
                year = None
            else:
                title_only = base
                year = None
        else:
            # We extract both title and year
            title_only = title_match.group('title').strip()
            year = int(title_match.group('year'))
        # Finally, we return the parsed TV show artwork metadata with as much data as possible
        artwork = {
            "media": "TV Show",
            "title": title_only,
            "year": year,
            "season": season,
            "episode": episode,
            "type": type,
            "author": None
        }
        debug_me(
            f"Matched '{title}' as TV Show {"Title Card" if episode is not None else "Season Cover"} "
            + f"for '{artwork['title']}{f" ({artwork['year']})" if artwork['year'] else ''}', "
            + f"Season {artwork['season']}{f", Episode {artwork['episode']}" if artwork['episode'] is not None else ''}", "media_metadata/parse_title"
        )
        return artwork

    # If we got to this point, we know it's not an episode or season cover, so we check for other types
    # Check if it's a background (if it matches it's a background but if it doesn't it could still be because not all background files contain "Backdrop" in the title)
    # So we'll check later based on image orientation (landscape means background) in web_routes.py / extract_and_list_zip function
    background_match = re.match(background_pattern, title, re.IGNORECASE)
    if background_match:
        artwork = {
            "media": "Unknown",
            "title": background_match.group('title').strip(),
            "year": background_match.group('year'),
            "season": "Backdrop",
            "episode": None,
            "type": "background",
            "author": None
        }
        debug_me(f"Matched '{title}' as either movie, TV show or collection background for '{artwork['title']} ({artwork['year']})'", "media_metadata/parse_title")
        return artwork

    # If we got to this point and it doesn't contain "Backdrop", it could still be a background or a movie ot tv show poster
    # We'll assume initially it's a movie poster if it matches the movie/show pattern (because it has a year in parentheses)
    movie_or_show_match = re.match(movie_or_show_pattern, title, re.IGNORECASE)
    if movie_or_show_match:
        artwork = {
            "media": "Unknown",
            "title": movie_or_show_match.group('title').strip(),
            "year": movie_or_show_match.group('year'),
            "season": None,
            "episode": None,
            "type": "poster",
            "author": None
        }
        debug_me(f"Matched '{title}' as either Movie or TV Show poster for '{artwork['title']} ({artwork['year']})'", "media_metadata/parse_title")
        return artwork

    # At the point we can only check if it's a collection (case insensitive)
    collection_match = re.match(collection_pattern, title, re.IGNORECASE)
    if collection_match:
        artwork = {
            "media": "Collection",
            "title": title.removesuffix(" - Backdrop").strip(),  # Remove trailing " - Backdrop" if present
            "year": None,
            "season": None,
            "episode": None,
            "type": "collection_poster",
            "author": None
        }
        debug_me(f"Matched '{title}' as Collection poster for '{artwork['title']}'", "media_metadata/parse_title")
        return artwork

    # If none of the above matched, return unknown
    return {"media": "Unknown", "message": "The title format is unrecognized."}




