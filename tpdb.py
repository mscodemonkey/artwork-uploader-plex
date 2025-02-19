import math

import soup_utils


def scrape_link_to_set(soup):
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
    movieposters_sets = []
    showposters_sets = []
    collectionposters_sets = []

    print("⚲ Looking for additional sets...")

    mt4s = soup.find('main').find_all('div', class_='mt-4')

    for mt4 in mt4s:

        additional_set = mt4.find('p').find('span').getText()

        if additional_set[:16] == "Additional Set -":

            print(f"+ {additional_set}")

            # find the poster grid
            poster_divs = mt4.find_all('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')
            poster_div = poster_divs[-1]

            set_url = scrape_link_to_set(poster_div)

            if set_url is not None:
                some_more_soup = soup_utils.cook_soup(set_url)
                more_movieposters, more_showposters, more_collectionposters = scrape_posters(some_more_soup)

                movieposters_sets = movieposters_sets + more_movieposters
                showposters_sets = showposters_sets + more_showposters
                collectionposters_sets = collectionposters_sets + more_collectionposters

    return movieposters_sets, showposters_sets, collectionposters_sets


def scrape_additional_posters(soup):
    movieposters_additional = []
    showposters_additional = []
    collectionposters_additional = []

    print("⚲ Looking for additional posters...")

    # find the poster grid
    poster_divs = soup.find_all('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')
    poster_div = poster_divs[-1]

    mt4s = soup.find('main').find_all('div', class_='mt-4')
    if len(mt4s) > 0:
        last_mt4 = mt4s[-1]
        additional_posters = last_mt4.find('p').find('span').getText()

        if additional_posters == "Additional Posters":
            movieposters_additional, showposters_additional, collectionposters_additional = get_posters(
                poster_div)

    return movieposters_additional, showposters_additional, collectionposters_additional


def get_posters(poster_div):
    movieposters = []
    showposters = []
    collectionposters = []

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

            showposter = {}
            showposter["title"] = title
            showposter["url"] = poster_url
            showposter["season"] = season
            showposter["episode"] = None
            showposter["year"] = year
            showposter["source"] = "posterdb"
            showposters.append(showposter)

        elif media_type == "Movie":
            title_split = title_p.split(" (")
            if len(title_split[1]) != 5:
                title = title_split[0] + " (" + title_split[1]
            else:
                title = title_split[0]
            year = title_split[-1].split(")")[0]

            movieposter = {}
            movieposter["title"] = title
            movieposter["url"] = poster_url
            movieposter["year"] = int(year)
            movieposter["source"] = "posterdb"
            movieposters.append(movieposter)

        elif media_type == "Collection":
            collectionposter = {}
            collectionposter["title"] = title_p
            collectionposter["url"] = poster_url
            collectionposter["source"] = "posterdb"
            collectionposters.append(collectionposter)

    return movieposters, showposters, collectionposters


def scrape_posters(soup):

    # find the poster grid
    poster_div = soup.find('div', class_='row d-flex flex-wrap m-0 w-100 mx-n1 mt-n1')

    return get_posters(poster_div)