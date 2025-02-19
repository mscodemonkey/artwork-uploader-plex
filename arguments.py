import argparse

# Parse the command line arguments.  They are all optional.
# ---------------------------------------------------------
# command           Leave blank for interactive mode, or use "bulk" or "gui" or a TPDb or Mediux poster set URL
# bulk_file         The bulk file name to load and process
# --add-sets        Adds ALL the "additional set" sections from TPDb page as well as the main posters
# --add-posters     Adds the "additional posters" section from TPDb page as well as the main posters
# --force           Forces each poster to upload even, if the same artwork is already there according to the label.

def parse_arguments():

    parser = argparse.ArgumentParser()

    # Adds all the arguments we might want to use
    parser.add_argument('command', help="Run mode (leave blank for interactive)", nargs='?', default=None)
    parser.add_argument('bulk_file', help="Bulk file (when using bulk as run mode)", nargs='?', default=None)
    parser.add_argument('--add-sets', action='store_true', help="Scrape additional sets from same page - TPDb only")
    parser.add_argument('--add-posters', action='store_true', help="Scrape additional posters from same page - TPDb only")
    parser.add_argument('--force', action='store_true', help="Force upload even if its the same artwork")

    return parser.parse_args()
