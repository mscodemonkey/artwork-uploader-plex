from config import Config
from options import Options
from plex_uploader import PlexUploader
from upload_processor_exceptions import CollectionNotFound, MovieNotFound, NotProcessedByFilter, ShowNotFound, \
    NotProcessedByExclusion
from utils import is_numeric
import re

class UploadProcessor:

    def __init__(self, plex):
        self.plex = plex
        self.options = Options()
        self.config = Config()
        self.config.load()

    def set_options(self, options):
        self.options = options

    def check_master_filters(self, check_filter, source):
        master_filters = self.config.tpdb_filters if source == "theposterdb" else self.config.mediux_filters
        return check_filter in master_filters if master_filters else True

    def process_collection_artwork(self, artwork):

        collection_items = self.plex.find_collection(artwork["title"])

        if not collection_items:
            collection_items = self.plex.find_collection(artwork["title"].replace(" Collection",""))

        result = None
        artwork_source = artwork["source"]
        filter_type = "collection_poster"

        if collection_items:
            for collection_item in collection_items:
                if (self.options.has_no_filters() and self.check_master_filters(filter_type,artwork_source)) or self.options.has_filter(filter_type):
                    if not self.options.is_excluded(artwork["id"]):
                        uploader = PlexUploader(collection_item, "Poster","P")
                        uploader.set_artwork(artwork)
                        uploader.track_artwork_ids = self.config.track_artwork_ids
                        uploader.set_description(f"{artwork['title']} : {artwork['id']}")
                        uploader.set_options(self.options)
                        result = uploader.upload_to_plex()
                    else:
                        raise NotProcessedByExclusion(
                            f"{artwork['title']} : {artwork['id']} | Poster excluded")
                else:
                    raise NotProcessedByFilter(f"{artwork['title']} : {artwork['id']} | Poster not processed due to {'requested' if not self.options.has_filter(filter_type) else artwork_source} filtering")
        else:
            raise CollectionNotFound(f'{artwork["title"]}: {artwork["id"]} | Collection not available on Plex')
        return result

    def process_movie_artwork(self, artwork):

        year = self.options.year if self.options.year else artwork["year"]

        movie_items = self.plex.find_in_library("movie", artwork["title"], year)

        # If no match is found, modify the title to replace dashes - this is useful for file uploads where colons have been replaced with dashes to comply with filesystem rules
        if not movie_items:
            # Replace the hyphen directly after a word with a colon (no space before it)
            modified_title = re.sub(r'(\w)-', r'\1:', artwork["title"])
            movie_items = self.plex.find_in_library("movie", modified_title, year)

        result = None
        artwork_source = artwork["source"]
        filter_type = "movie_poster"

        if movie_items:
            for movie_item in movie_items:
                if (self.options.has_no_filters() and self.check_master_filters(filter_type,artwork_source)) or self.options.has_filter(filter_type):
                    if not self.options.is_excluded(artwork["id"]):
                        uploader = PlexUploader(movie_item, "Poster", artwork_id="P")
                        uploader.set_artwork(artwork)
                        uploader.track_artwork_ids = self.config.track_artwork_ids
                        uploader.set_description(f"{artwork['title']} : {artwork['id']}")
                        if artwork['year']:
                            uploader.set_description(f"{artwork['title']} ({artwork['year']}) : {artwork['id']}")
                        uploader.set_options(self.options)
                        result = uploader.upload_to_plex()
                    else:
                        raise NotProcessedByExclusion(f"{artwork['title']} ({artwork['year']}) | {artwork['id']} | Poster excluded")
                else:
                    raise NotProcessedByFilter(f"{artwork['title']} ({artwork['year']}) | {artwork['id']} | Poster filtered by {'request' if not self.options.has_filter(filter_type) else artwork_source}")
        else:
            raise MovieNotFound(f'{artwork["title"]} ({artwork["year"]}) | {artwork["id"]} | Movie not available on Plex')
        return result


    def process_tv_artwork(self, artwork):

        description = "Target media"
        upload_target = None
        artwork_type = None
        filter_type = None
        artwork_id = None
        artwork_source = artwork["source"]
        result = "none"

        season = artwork['season']
        if is_numeric(season) and season == 0:
            season = "Specials"
        else:
            season = f"Season {artwork['season']:02}"
#
        if is_numeric(artwork['season']) and is_numeric(artwork['episode']):
            description = f"{artwork['title']} | {season}, Episode {artwork['episode']:02} : {artwork['id']}"
        elif (artwork['episode'] is None or artwork['episode'] == "Cover") and is_numeric(artwork['season']):
            description = f"{artwork['title']} | {season} : {artwork['id']}"
        elif artwork['season'] is None or artwork["season"] == "Cover" or artwork["season"] == "Backdrop":
            description = f"{artwork['title']} : {artwork['id']}"

        year = self.options.year if self.options.year else artwork["year"]

        tv_show_items = self.plex.find_in_library("tv", artwork["title"], year )

        # If no match is found, modify the title to replace dashes - this is useful for file uploads where colons have been replaced with dashes to comply with filesystem rules
        if not tv_show_items:
            # Replace the hyphen directly after a word with a colon (no space before it)
            modified_title = re.sub(r'(\w)-', r'\1:', artwork["title"])
            tv_show_items = self.plex.find_in_library("tv", modified_title, year)

        if tv_show_items:
            for tv_show in tv_show_items:
                try:
                    if artwork["season"] == "Cover":
                        upload_target = tv_show
                        artwork_id = "C"
                        artwork_type = "Show cover"
                        filter_type = "show_cover"
                    elif artwork["season"] == "Backdrop":
                        upload_target = tv_show
                        artwork_id = "B"
                        artwork_type = "Background"
                        filter_type="background"
                    elif artwork["season"] >= 0:
                        if artwork["episode"] == "Cover":
                            upload_target = tv_show.season(artwork["season"])
                            artwork_id = "S"
                            artwork_type = "Season cover"
                            filter_type = "season_cover"
                        elif artwork["episode"] is None:
                            upload_target = tv_show.season(artwork["season"])
                            artwork_id = "S"
                            artwork_type = "Season cover"
                            filter_type = "season_cover"
                        elif artwork["episode"] >= 0:
                            upload_target = tv_show.season(artwork["season"]).episode(artwork["episode"])
                            artwork_id = "E"
                            artwork_type = "Title card"
                            filter_type = "title_card"
                except:
                    raise ShowNotFound(f"{description} | Not available on Plex")

                try:
                    if upload_target:
#                        print(f"Filters for {filter_type} in master for {artwork_source}: {self.check_master_filters(filter_type, artwork_source)} and requested: {self.options.has_filter(filter_type)}")
                        if (self.options.has_no_filters() and self.check_master_filters(filter_type, artwork_source)) or self.options.has_filter(filter_type):
                            if not self.options.is_excluded(artwork["id"]):
                                uploader = PlexUploader(upload_target, artwork_type, artwork_id)
                                uploader.set_artwork(artwork)
                                uploader.track_artwork_ids = self.config.track_artwork_ids
                                uploader.set_description(description)
                                uploader.set_options(self.options)
                                result = uploader.upload_to_plex()
                            else:
                                raise NotProcessedByExclusion(f"{description} | {artwork_type} excluded")
                        else:
                            raise NotProcessedByFilter(f"{description} | {artwork_type} not processed due to {'requested' if not self.options.has_filter(filter_type) else artwork_source} filtering")
                except Exception:
                    raise
        else:
            raise ShowNotFound(f"{artwork['title']} ({artwork['year']}) | Show not available on Plex")

        return result


