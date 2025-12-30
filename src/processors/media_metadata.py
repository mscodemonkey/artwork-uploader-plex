from core.constants import (
    SEASON_COVER, SEASON_BACKDROP, SEASON_SPECIALS,
    MEDIA_TYPE_TV_SHOW, MEDIA_TYPE_COLLECTION,
    FILTER_TITLE_CARD, FILTER_SEASON_COVER, FILTER_BACKGROUND
)
from utils.notifications import debug_me


def parse_show(media_title):
    title = media_title.split(" (")[0]
    year = None
    season = SEASON_COVER

    try:
        year = int(media_title.split(" (")[1].split(")")[0])
    except (IndexError, ValueError):
        pass

    if " - " in media_title:
        split_season = media_title.split(" - ")[-1]
        if split_season == SEASON_SPECIALS:
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
    except (AttributeError, ValueError, TypeError):
        debug_me(f"Couldn't match {movie_title}", "parse_movie")
        return None, None


import re


def parse_title(title: str):
    # Strip any trailing spaces before the extension
    title = re.sub(r"\s+\.", ".", title).strip()

    # Regular expression patterns to match TV shows, movies, collections, episodes, and backgrounds
    episode_pattern = r".*S(?P<season>\d+)\sE(?P<episode>\d+).*"
    season_pattern = r".*Season\s(?P<season>\d+).*"
    specials_pattern = rf".*- {SEASON_SPECIALS}.*"
    title_pattern_with_year = r"^(?P<title>.+)\s\((?P<year>\d{4})\)$"
    title_pattern_without_year = r"^(?P<title>.+)$"

    movie_or_show_pattern = r"^(?P<title>.+)\s\((?P<year>\d{4})\)"
    background_pattern = rf"^(?P<title>.+)\s\((?P<year>\d{4})\)\s-\s{SEASON_BACKDROP}"
    collection_pattern = r"^(?!.*\(\d{4}\))(?P<title>.+)$"  # Some collection poster files don't have the word "Collection" in them

    episode_match = re.match(episode_pattern, title, re.IGNORECASE)
    if episode_match:
        season = int(episode_match.group('season'))
        episode = int(episode_match.group('episode'))
        type = FILTER_TITLE_CARD
        base = re.split(r"\s-\sS\d+\s*E\d+.*", title, 1)[0].strip()

    season_match = re.match(season_pattern, title, re.IGNORECASE)
    if season_match:
        season = int(season_match.group('season'))
        episode = None
        type = FILTER_SEASON_COVER
        base = re.split(r"\s-\sSeason\s\d+.*", title, 1)[0].strip()

    specials_match = re.match(specials_pattern, title, re.IGNORECASE)
    if specials_match:
        season = 0
        episode = None
        type = FILTER_SEASON_COVER
        base = re.split(rf"\s-\s{SEASON_SPECIALS}.*", title, 1)[0].strip()

    if episode_match or season_match or specials_match:
        title_match = re.match(title_pattern_with_year, base)
        if not title_match:
            title_match = re.match(title_pattern_without_year, base)
            if title_match:
                title_only = title_match.group('title').strip()
                year = None
            else:
                title_only = base
                year = None
        else:
            title_only = title_match.group('title').strip()
            year = int(title_match.group('year'))
        artwork = {
            "media": MEDIA_TYPE_TV_SHOW,
            "title": title_only,
            "year": year,
            "season": season,
            "episode": episode,
            "type": type,
            "author": None
        }
        debug_me(
            f"Matched '{title}' as TV Show {"Title Card" if episode is not None else "Season Cover"} for '{artwork['title']}{f" ({artwork['year']})" if artwork['year'] else ''}', Season {artwork['season']}{f", Episode {artwork['episode']}" if artwork['episode'] is not None else ''}",
            "media_metadata/parse_title")
        return artwork

    # Check if it's a TV show background
    background_match = re.match(background_pattern, title, re.IGNORECASE)
    if background_match:
        artwork = {
            "media": MEDIA_TYPE_TV_SHOW,
            "title": background_match.group('title').strip(),
            "year": background_match.group('year'),
            "season": SEASON_BACKDROP,
            "episode": None,
            "type": FILTER_BACKGROUND,
            "author": None
        }
        debug_me(f"Matched '{title}' as TV Show Background for '{artwork['title']} ({artwork['year']})'",
                 "media_metadata/parse_title")
        return artwork

    # Check if it's a movie
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
        debug_me(f"Matched '{title}' as either Movie or TV Show poster for '{artwork['title']} ({artwork['year']})'",
                 "media_metadata/parse_title")
        return artwork

    # Check if it's a collection (case insensitive)
    collection_match = re.match(collection_pattern, title, re.IGNORECASE)
    if collection_match:
        artwork = {
            "media": MEDIA_TYPE_COLLECTION,
            "title": title.strip(),
            "season": None,
            "episode": None,
            "type": "collection poster",
            "author": None
        }
        debug_me(f"Matched '{title}' as Collection poster for '{artwork['title']}'", "media_metadata/parse_title")
        return artwork

    return {"media": "Unknown", "message": "The title format is unrecognized."}
