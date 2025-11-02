from typing import Optional
import re

from core.config import Config
from models.options import Options
from plex.plex_connector import PlexConnector
from plex.plex_uploader import PlexUploader
from plexapi.exceptions import NotFound
from kometa.kometa_saver import KometaSaver
from core.exceptions import CollectionNotFound, MovieNotFound, NotProcessedByFilter, ShowNotFound, \
    NotProcessedByExclusion
from utils.utils import is_numeric, get_path_parts
from core.enums import FilterType, ScraperSource
from models.artwork_types import MovieArtwork, TVArtwork, CollectionArtwork
from pprint import pprint
import os
from core import globals
from utils.notifications import debug_me
#from pathlib import PureWindowsPath, PurePosixPath

class UploadProcessor:

    def __init__(self, plex: PlexConnector) -> None:
        self.plex: PlexConnector = plex
        self.options: Options = Options()
        self.config: Config = Config()
        self.config.load()

    def set_options(self, options: Options) -> None:
        self.options = options

    def check_master_filters(self, check_filter: str, source: str) -> bool:
        master_filters = self.config.tpdb_filters if source == ScraperSource.THEPOSTERDB.value else self.config.mediux_filters
        return check_filter in master_filters if master_filters else True

    def process_collection_artwork(self, artwork: CollectionArtwork) -> Optional[str]:

        collection_items, libraries = self.plex.find_collection(artwork["title"])

        if not collection_items:
            collection_items, libraries = self.plex.find_collection(artwork["title"].replace(" Collection",""))

        result = None
        results = []
        artwork_source = artwork["source"]
        description = f"{artwork["title"]} : {artwork["id"]}"
        filter_type = FilterType.COLLECTION_POSTER.value if artwork["type"] == "collection poster" else FilterType.BACKGROUND.value
        artwork_type = "Poster" if artwork["type"] == "collection poster" else "Background"
        artwork_id = artwork_type[0]
        #artwork_id = "P" if artwork["type"] == "collection poster" else "B"

        if collection_items:
            debug_me(f"Found collection '{artwork["title"]}' in {len(libraries)} libraries.", "UploadProcessor/process_movie_artwork")
            for collection_item, library in zip(collection_items, libraries):
                if (self.options.has_no_filters() and self.check_master_filters(filter_type,artwork_source)) or self.options.has_filter(filter_type):
                    if not self.options.is_excluded(artwork["id"]):
                        if self.options.kometa or globals.config.save_to_kometa:
                            asset_folder = collection_item.title
                            saver = KometaSaver(artwork_type, library)
                            saver.set_artwork(artwork)
                            if os.getenv("RUNNING_IN_DOCKER") == "1":
                                base_dir = "/temp" if self.options.temp else "/assets"
                            else:
                                base_dir = getattr(globals.config, "temp_dir" if self.options.temp else "kometa_base", None)
                            saver.dest_dir = os.path.join(base_dir, library, asset_folder)
                            debug_me(f"Destination directory is {saver.dest_dir}", "UploadProcessor/process_collection_artwork")
                            #saver.dest_file_name = "poster" if artwork["type"] == "collection poster" else "background"
                            saver.dest_file_name = artwork_type.lower()
                            saver.dest_file_ext = ".jpg"
                            saver.set_description(description)
                            saver.set_options(self.options)
                            result = saver.save_to_kometa()
                            results.append(result)
                        else:
                            uploader = PlexUploader(collection_item, artwork_type, artwork_id)
                            uploader.set_artwork(artwork)
                            uploader.track_artwork_ids = self.config.track_artwork_ids
                            uploader.reset_overlay = self.config.reset_overlay
                            uploader.set_description(description)
                            uploader.set_options(self.options)
                            result = uploader.upload_to_plex()
                            results.append(result)
                    else:
                        raise NotProcessedByExclusion(
                            f"{description} | Poster excluded")
                else:
                    raise NotProcessedByFilter(f"{description} | {artwork_type} not processed due to {'requested' if not self.options.has_filter(filter_type) else artwork_source} filtering")
        else:
            raise CollectionNotFound(f'{description} | Collection not available on Plex')
        return results

    def process_movie_artwork(self, artwork: MovieArtwork) -> Optional[str]:

        year = self.options.year if self.options.year else artwork["year"]

        movie_items, libraries = self.plex.find_in_library("movie", artwork["title"], year)
        
        # If no match is found, modify the title to replace dashes - this is useful for file uploads where colons have been replaced with dashes to comply with filesystem rules
        if not movie_items:
            # Replace the hyphen directly after a word with a colon (no space before it)
            modified_title = re.sub(r'(\w)-', r'\1:', artwork["title"])
            debug_me(f"Movie '{artwork["title"]} ({year})' not found, trying with modified tile '{modified_title}'", "UploadProcessor/process_movie_artwork")
            movie_items, libraries = self.plex.find_in_library("movie", modified_title, year)

        # If still no match is found, try some other options
        if not movie_items:
            # Replace three-dot elipsis (...) with the single unicode character elipsis (…)
            modified_title = artwork["title"].replace("...","…")
            debug_me(f"Movie '{artwork["title"]} ({year})' not found, trying with modified tile '{modified_title}'", "UploadProcessor/process_movie_artwork")
            movie_items, libraries = self.plex.find_in_library("movie", modified_title, year)

        result = None
        results = []
        artwork_source = artwork["source"]
        description = f"{artwork["title"]} ({artwork["year"]}) : {artwork["id"]}"
        filter_type = FilterType.MOVIE_POSTER.value if artwork["type"] == "poster" else FilterType.BACKGROUND.value
        artwork_type = "Poster" if artwork["type"] == "poster" else "Background"
        artwork_id = artwork_type[0]
        #artwork_type = "P" if artwork["type"] == "poster" else "B"

        if movie_items:
            debug_me(f"Found movie '{artwork["title"]} ({artwork["year"]})' in {len(libraries)} libraries.", "UploadProcessor/process_movie_artwork")
            for movie_item, library in zip(movie_items, libraries):
                if (self.options.has_no_filters() and self.check_master_filters(filter_type,artwork_source)) or self.options.has_filter(filter_type):
                    if not self.options.is_excluded(artwork["id"]):
                        if self.options.kometa or globals.config.save_to_kometa:
                            item_path = movie_item.media[0].parts[0].file
                            path_parts = []
                            path_parts = get_path_parts(item_path)
                            asset_folder = path_parts[-2]
                            saver = KometaSaver(artwork_type, library)
                            saver.set_artwork(artwork)
                            if os.getenv("RUNNING_IN_DOCKER") == "1":
                                base_dir = "/temp" if self.options.temp else "/assets"
                            else:
                                base_dir = getattr(globals.config, "temp_dir" if self.options.temp else "kometa_base", None)
                            saver.dest_dir = os.path.join(base_dir, library, asset_folder)
                            debug_me(f"Destination directory is {saver.dest_dir}", "UploadProcessor/process_movie_artwork")
                            #saver.dest_file_name = "poster" if artwork["type"] == "poster" else "background"
                            saver.dest_file_name = artwork_type.lower()
                            saver.dest_file_ext = ".jpg"
                            saver.set_description(description)
                            saver.set_options(self.options)
                            result = saver.save_to_kometa()
                            results.append(result)
                        else:
                            uploader = PlexUploader(movie_item, artwork_type, artwork_id)
                            uploader.set_artwork(artwork)
                            uploader.track_artwork_ids = self.config.track_artwork_ids
                            uploader.reset_overlay = self.config.reset_overlay
                            uploader.set_description(f"{artwork['title']} : {artwork['id']}")
                            if artwork['year']:
                                uploader.set_description(description)
                            uploader.set_options(self.options)
                            result = uploader.upload_to_plex()
                            results.append(result)
                    else:
                        raise NotProcessedByExclusion(f"{description} | {artwork_type} Poster excluded")
                else:
                    raise NotProcessedByFilter(f"{description} | {artwork_type} filtered by {'request' if not self.options.has_filter(filter_type) else artwork_source}")
        else:
            raise MovieNotFound(f'{description} | Movie not available on Plex')
        return results


    def process_tv_artwork(self, artwork: TVArtwork) -> Optional[str]:

        description = "Target media"
        upload_target = None
        artwork_type = None
        filter_type = None
        artwork_id = None
        artwork_source = artwork["source"]
        result = "none"
        results = []

        season = artwork['season']
        if is_numeric(season) and season == 0:
            season = "Specials"
        else:
            season = f"Season {artwork['season']:02}"
#
        if is_numeric(artwork['season']) and is_numeric(artwork['episode']):
            description = f"{artwork['title']} : {season}, Episode {artwork['episode']:02} : {artwork['id']}"
        elif (artwork['episode'] is None or artwork['episode'] == "Cover") and is_numeric(artwork['season']):
            description = f"{artwork['title']} : {season} : {artwork['id']}"
        elif artwork['season'] is None or artwork["season"] == "Cover" or artwork["season"] == "Backdrop":
            description = f"{artwork['title']} : {artwork['id']}"

        year = self.options.year if self.options.year else artwork["year"]

        tv_show_items, libraries = self.plex.find_in_library("tv", artwork["title"], year )

        # If no match is found, modify the title to replace dashes - this is useful for file uploads where colons have been replaced with dashes to comply with filesystem rules
        if not tv_show_items:
            # Replace the hyphen directly after a word with a colon (no space before it)
            modified_title = re.sub(r'(\w)-', r'\1:', artwork["title"])
            debug_me(f"TV Show '{artwork["title"]} ({year})' not found, trying with modified tile '{modified_title}'", "UploadProcessor/process_tv_artwork")
            tv_show_items, libraries = self.plex.find_in_library("tv", modified_title, year)

        if not tv_show_items:
            # Remove colons and replace three-dot elipsis (...) with the single unicode character elipsis (…)
            modified_title = artwork["title"].replace(":","").replace("...","…")
            debug_me(f"TV Show '{artwork["title"]} ({year})' not found, trying with modified tile '{modified_title}'", "UploadProcessor/process_tv_artwork")
            tv_show_items, libraries = self.plex.find_in_library("tv", modified_title, year)
        
        if tv_show_items:
            debug_me(f"Found TV Show '{artwork["title"]} ({artwork["year"]})' in {len(libraries)} libraries.", "UploadProcessor/process_movie_artwork")
            for tv_show, library in zip(tv_show_items, libraries):
                item_path = tv_show.seasons()[0].episodes()[0].media[0].parts[0].file
                path_parts = []
                path_parts = get_path_parts(item_path)
                asset_folder = path_parts[-3]
                #asset_folder = os.path.basename(os.path.dirname(os.path.dirname(tv_show.seasons()[0].episodes()[0].media[0].parts[0].file)))
                try:
                    if artwork["season"] == "Cover":
                        upload_target = tv_show
                        artwork_id = "C"
                        artwork_type = "Show cover"
                        file_name = "poster"
                        filter_type = FilterType.SHOW_COVER.value
                    elif artwork["season"] == "Backdrop":
                        upload_target = tv_show
                        artwork_id = "B"
                        artwork_type = "Background"
                        file_name = "background"
                        filter_type = FilterType.BACKGROUND.value
                    elif artwork["season"] >= 0:
                        if artwork["episode"] == "Cover" or artwork["episode"] is None:
                            if artwork["season"] in [S.index for S in tv_show.seasons()]:
                                upload_target = tv_show.season(artwork["season"])
                                artwork_id = "S"
                                artwork_type = "Season cover"
                                file_name = f"Season{artwork["season"]:02}"
                                filter_type = FilterType.SEASON_COVER.value
                            else:
                                result = f"∙ {description} | {season} not available in {library}"
                                results.append(result)
                                continue
                        elif artwork["episode"] >= 0:
                            if (artwork["season"] in [S.index for S in tv_show.seasons()]):
                                if (artwork["episode"] in [E.index for E in tv_show.season(artwork["season"]).episodes()]) or (self.options.kometa or globals.config.save_to_kometa):
                                    if not(self.options.kometa or globals.config.save_to_kometa):
                                        upload_target = tv_show.season(artwork["season"]).episode(artwork["episode"])
                                    artwork_id = "E"
                                    artwork_type = "Title card"
                                    file_name = f"S{artwork["season"]:02}E{artwork["episode"]:02}"
                                    filter_type = FilterType.TITLE_CARD.value
                                else:
                                    result = f"∙ {description} | {season}, Episode {artwork["episode"]:02} not available in {library}"
                                    results.append(result)
                                    continue
                            else:
                                result = f"∙ {description} | {season} not available in {library}"
                                results.append(result)
                                continue

                except (AttributeError, KeyError, NotFound) as e:
                    raise ShowNotFound(f"{description} | Not available on Plex in {library}: {e}") from e
                    
                try:
                    if upload_target or (self.options.kometa or globals.config.save_to_kometa):
                        if (self.options.has_no_filters() and self.check_master_filters(filter_type, artwork_source)) or self.options.has_filter(filter_type):
                            # Pass season/episode info for TV show exclusion checks
                            season_num = artwork['season'] if isinstance(artwork['season'], int) else None
                            episode_num = artwork['episode'] if isinstance(artwork['episode'], int) else None
                            if not self.options.is_excluded(artwork["id"], season_num, episode_num):
                                if self.options.kometa or globals.config.save_to_kometa:
                                    saver = KometaSaver(artwork_type, library)
                                    saver.set_artwork(artwork)
                                    if os.getenv("RUNNING_IN_DOCKER") == "1":
                                        base_dir = "/temp" if self.options.temp else "/assets"
                                    else:
                                        base_dir = getattr(globals.config, "temp_dir" if self.options.temp else "kometa_base", None)
                                    saver.dest_dir = os.path.join(base_dir, library, asset_folder)
                                    debug_me(f"Destination directory is {saver.dest_dir}", "UploadProcessor/process_tv_artwork")
                                    saver.dest_file_name = file_name
                                    saver.dest_file_ext = ".jpg"
                                    saver.set_description(description)
                                    saver.set_options(self.options)
                                    result = saver.save_to_kometa()
                                    results.append(result)
                                else:
                                    uploader = PlexUploader(upload_target, artwork_type, artwork_id)
                                    uploader.set_artwork(artwork)
                                    uploader.track_artwork_ids = self.config.track_artwork_ids
                                    uploader.reset_overlay = self.config.reset_overlay
                                    uploader.set_description(description)
                                    uploader.set_options(self.options)
                                    result = uploader.upload_to_plex()
                                    results.append(result)
                            else:
                                raise NotProcessedByExclusion(f"{description} | {artwork_type} excluded")
                        else:
                            raise NotProcessedByFilter(f"{description} | {artwork_type} not processed due to {'requested' if not self.options.has_filter(filter_type) else artwork_source} filtering")
                except Exception:
                    raise
        else:
            raise ShowNotFound(f"{description} | Show not available on Plex")

        return results

