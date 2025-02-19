from bs4 import BeautifulSoup

import soup_utils
import tpdb
import mediux
import sys
import plex_upload


def scrape_single_url(url, options):

    movie_posters = []
    show_posters = []
    collection_posters = []

    # First let's handle ThePosterDB and see if we've been passed a link to a poster set

    if url and ("theposterdb.com" in url):

        # If we were passed a poster link, it should have a link to its corresponding poster set.
        # Even if it's just one poster, it still has a poster set.  So let's find that link and get its contents.

        if "/poster/" in url:

            print(f"★ Got a poster URL {url}, looking up the correct set URL...")
            soup = soup_utils.cook_soup(url)
            url = tpdb.scrape_link_to_set(soup)

        if url and ("/set/" in url or "/user/" in url):

            soup = soup_utils.cook_soup(url)

            # Get the standard set of posters on the TPDb page
            movies, shows, collections = tpdb.scrape_posters(soup)
            movie_posters.extend(movies)
            show_posters.extend(shows)
            collection_posters.extend(collections)

            # Get the additional posters if required
            if options.add_posters:
                movies, shows, collections = tpdb.scrape_additional_posters(soup)
                movie_posters.extend(movies)
                show_posters.extend(shows)
                collection_posters.extend(collections)

            # Get the additional sets if required
            if options.add_sets:
                movies, shows, collections = tpdb.scrape_additional_sets(soup)
                movie_posters.extend(movies)
                show_posters.extend(shows)
                collection_posters.extend(collections)

            return movie_posters, show_posters, collection_posters

        else:
            sys.exit("x Poster set not found. Check the link you are using.")


    # Now let's handle a link to mediux.pro - this could be anything from a backdrop, posters or episode cards

    elif url and (("mediux.pro" in url) and ("sets" in url)):
        soup = soup_utils.cook_soup(url)
        return mediux.scrape_mediux(soup)


    # Not sure what this option is - I'm guessing it was a saved page used so that TPDb wasn't hammered during development

    elif url and (".html" in url):
        with open(url, 'r', encoding='utf-8') as file:
            html_content = file.read()
        soup = BeautifulSoup(html_content, 'html.parser')
        return tpdb.scrape_posters(soup)

    else:
        sys.exit("x Poster set not found. Check the link you are inputting.")

# Scrape all pages of a user's uploads.
def scrape_entire_user_portfolio(url, options, tv, movies):

    soup = soup_utils.cook_soup(url)
    pages = tpdb.scrape_user_info(soup)

    if not pages:
        print(f"x Could not determine the number of pages for {url}")
        return

    if "?" in url:
        cleaned_url = url.split("?")[0]
        url = cleaned_url

    for page in range(pages):
        # print(f"+ Scraping page {page + 1}.")
        page_url = f"{url}?section=uploads&page={page + 1}"

        # print (f"Scraping {page_url}")
        # a, b, c = scrape_single_url(page_url, options)
        # print(f"{len(a)} movie posters, {len(b)} show posters and {len(c)} collection posters on this page")

        process_url_and_upload_scraped_posters(page_url, options, tv, movies)


def process_url_and_upload_scraped_posters(url, options, tv, movies):

    # Let's scrape the posters first
    movieposters, showposters, collectionposters = scrape_single_url(url, options)

    # Now upload them to Plex
    for poster in collectionposters:
        plex_upload.collection_poster(poster, movies, options)

    for poster in movieposters:
        plex_upload.movie_poster(poster, movies, options)

    for poster in showposters:
        plex_upload.tv_artwork(poster, tv, options)


