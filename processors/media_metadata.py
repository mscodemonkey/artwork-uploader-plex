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
    tv_show_pattern = r"^(?P<title>[\w\s\-]+)\s\((?P<year>\d{4})\)\s-\s(Season\s(?P<season_number>\d+)|Specials)"
    tv_episode_pattern = r"^(?P<title>[\w\s\-]+)\s\((?P<year>\d{4})\)\s-\sS(?P<season_number>\d+)\sE(?P<episode_number>\d+)"
    movie_pattern = r"^(?P<title>[\w\s\-]+)\s\((?P<year>\d{4})\)"
    collection_pattern = r"^(?P<title>[\w\s\-]+Collection)$"
    background_pattern = r"^(?P<title>[\w\s\-]+)\s\((?P<year>\d{4})\)\s-\sBackdrop"

    # Check if it's a TV episode
    episode_match = re.match(tv_episode_pattern, title, re.IGNORECASE)
    if episode_match:
        return {
            "media": "TV Show",
            "title": episode_match.group('title').strip(),
            "year": episode_match.group('year'),
            "season": int(episode_match.group('season_number')),
            "episode": int(episode_match.group('episode_number'))
        }

    # Check if it's a TV show (season or specials)
    tv_match = re.match(tv_show_pattern, title, re.IGNORECASE)
    if tv_match:
        return {
            "media": "TV Show",
            "title": tv_match.group('title').strip(),
            "year": tv_match.group('year'),
            "season": int(tv_match.group('season_number')) if tv_match.group('season_number') else 0,
            "episode": None
        }

    # Check if it's a collection (case insensitive)
    collection_match = re.match(collection_pattern, title, re.IGNORECASE)
    if collection_match:
        return {
            "media": "Collection",
            "title": title.strip(),
            "season": None,
            "episode": None
        }

    # Check if it's a TV show background
    background_match = re.match(background_pattern, title, re.IGNORECASE)
    if background_match:
        return {
            "media": "TV Show",
            "title": background_match.group('title').strip(),
            "year": background_match.group('year'),
            "season": "Backdrop",
            "episode": None
        }

    # Check if it's a movie
    movie_match = re.match(movie_pattern, title, re.IGNORECASE)
    if movie_match:
        return {
            "media": "Movie",
            "title": movie_match.group('title').strip(),
            "year": movie_match.group('year'),
            "season": None,
            "episode": None

        }

    return {"media": "Unknown", "message": "The title format is unrecognized."}




