import argparse

# Parse the command line arguments.  They are all optional.
# ---------------------------------------------------------
# command           Leave blank for interactive mode, or use "bulk" or "gui" or a TPDb or Mediux poster set URL
# bulk_file         The bulk file name to load and process
# --add-sets        Adds ALL the "additional set" sections from TPDb page as well as the main posters
# --add-posters     Adds the "additional posters" section from TPDb page as well as the main posters
# --force           Forces each poster to upload even, if the same artwork is already there according to the label.
# --filters         Specify one or more filters, only these types will be applied (e.g., title_card, background, season_cover, show_cover, movie_poster, collection_poster)
# --exclude         Specify one or more IDs to exclude from any uploads

def parse_arguments():

    parser = argparse.ArgumentParser()

    # Adds all the arguments we might want to use
    parser.add_argument('command', help="Run mode (leave blank for interactive)", nargs='?', default=None)
    parser.add_argument('bulk_file', help="Bulk file (when using bulk as run mode)", nargs='?', default=None)
    parser.add_argument('--add-sets', action='store_true', help="Scrape additional sets from same page - TPDb only")
    parser.add_argument('--add-posters', action='store_true', help="Scrape additional posters from same page - TPDb only")
    parser.add_argument('--force', action='store_true', help="Force upload even if its the same artwork")
    parser.add_argument("--filters", nargs='+', help="Only these artwork types will be applied (e.g., title_card, background, season_cover, show_cover, movie_poster, collection_poster).")
    parser.add_argument("--exclude", nargs='+', help="Specify one or more IDs to exclude from any uploads.")
    parser.add_argument("--year", type=int, help="Override the year for matching (use the year in Plex)")
    parser.add_argument("--debug", action='store_true', help="Spits out debugging information")

    return parser.parse_args()
