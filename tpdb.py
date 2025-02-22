import json
import math
from html.parser import HTMLParser

import soup_utils
from utils import get_artwork_type


# ---------------------------------------------------------
# The main scraping functionality for ThePosterDB
# ---------------------------------------------------------
#
#
#
#


# Look for a link to a fiv with a class of view_all
def find_link_to_poster_set(soup):

    try:
        view_all_div = soup.find('a', class_='rounded view_all')['href']
    except:
        return None
    return view_all_div


def scrape_user_info(soup):
    try:
        span_tag = soup.find('span', class_='numCount')
        number_str = span_tag['data-count']

        upload_count = int(number_str)
        pages = math.ceil(upload_count / 24)
        return pages
    except:
        return None


def scrape_additional_sets(soup):
    movie_posters_sets = []
    show_posters_sets = []
    collection_posters_sets = []

    print("⚲ Looking for additional sets...")

    mt4s = soup.find('main').find_all('div', class_='mt-4')

    for mt4 in mt4s:

        additional_set = mt4.find('p').find('span').getText()

        if additional_set[:16] == "Additional Set -":

            print(f"+ {additional_set}")

            # find the poster grid
            poster_divs = mt4.find_all('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')
            poster_div = poster_divs[-1]

            set_url = find_link_to_poster_set(poster_div)

            if set_url is not None:
                some_more_soup = soup_utils.cook_soup(set_url)
                more_movie_posters, more_show_posters, more_collection_posters = scrape_posters(some_more_soup)

                movie_posters_sets = movie_posters_sets + more_movie_posters
                show_posters_sets = show_posters_sets + more_show_posters
                collection_posters_sets = collection_posters_sets + more_collection_posters

    return movie_posters_sets, show_posters_sets, collection_posters_sets


def scrape_additional_posters(soup):
    movie_posters_additional = []
    show_posters_additional = []
    collection_posters_additional = []

    print("⚲ Looking for additional posters...")

    # find the poster grid
    poster_divs = soup.find_all('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')
    poster_div = poster_divs[-1]

    mt4s = soup.find('main').find_all('div', class_='mt-4')
    if len(mt4s) > 0:
        last_mt4 = mt4s[-1]
        additional_posters = last_mt4.find('p').find('span').getText()

        if additional_posters == "Additional Posters":
            movie_posters_additional, show_posters_additional, collection_posters_additional = get_posters(
                poster_div)

    return movie_posters_additional, show_posters_additional, collection_posters_additional


def get_posters(poster_div):

    movie_posters = []
    show_posters = []
    collection_posters = []

    # find all poster divs
    posters = poster_div.find_all('div', class_='col-6 col-lg-2 p-1')

    if posters[-1].find('a', class_='rounded view_all'):
        posters.pop()

    # loop through the poster divs
    for poster in posters:

        # get if poster is for a show or movie
        media_type = poster.find('a', class_="text-white", attrs={'data-toggle': 'tooltip', 'data-placement': 'top'})[
            'title']

        # get high resolution poster image
        overlay_div = poster.find('div', class_='overlay')
        poster_id = overlay_div.get('data-poster-id')
        poster_url = "https://theposterdb.com/api/assets/" + poster_id

        # get metadata
        title_p = poster.find('p', class_='p-0 mb-1 text-break').string

        if media_type == "Show":
            title = title_p.split(" (")[0]
            try:
                year = int(title_p.split(" (")[1].split(")")[0])
            except:
                year = None

            if " - " in title_p:
                split_season = title_p.split(" - ")[-1]
                if split_season == "Specials":
                    season = 0
                elif "Season" in split_season:
                    season = int(split_season.split(" ")[1])
            else:
                season = "Cover"

            show_poster = {
                "title": title,
                "url": poster_url,
                "season": season,
                "episode": None,
                "year": year,
                "source": "theposterdb"
            }

            artwork_type, filter_type = get_artwork_type(show_poster)

            show_posters.append(show_poster)


        elif media_type == "Movie":
            title_split = title_p.split(" (")
            if len(title_split[1]) != 5:
                title = title_split[0] + " (" + title_split[1]
            else:
                title = title_split[0]
            year = title_split[-1].split(")")[0]

            movie_poster = {
                "title": title,
                "url": poster_url,
                "year": int(year),
                "source": "theposterdb"
            }
            movie_posters.append(movie_poster)

        elif media_type == "Collection":
            collection_poster = {
                "title": title_p,
                "url": poster_url,
                "source": "theposterdb"
            }
            collection_posters.append(collection_poster)

    return movie_posters, show_posters, collection_posters


def scrape_posters(soup):

    # find the poster grid
    poster_div = soup.find('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')

    return get_posters(poster_div)