import re

def parse_show(media_title):
    title = media_title.split(" (")[0]
    year = None
    season = "Cover"

    try:
        year = int(media_title.split(" (")[1].split(")")[0])
    except:
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
    match = re.match(r'^(.*?)(?:\s*\((\d{4})\))?$', movie_title.strip())

    if match:
        title = match.group(1).strip()
        year = int(match.group(2)) if match.group(2) else None
        return title, year
    return None, None