import os
from typing import Any

from core import globals
from core.config import Config
from core.constants import (
    SEASON_COVER, SEASON_BACKDROP, SEASON_SPECIALS,
    EPISODE_COVER, TPDB_BASE_URL
)
from core.enums import FilterType, ScraperSource
from core.exceptions import CollectionNotFound, MovieNotFound, NotProcessedByFilter, ShowNotFound, \
    NotProcessedByExclusion
from kometa.kometa_saver import KometaSaver
from models.artwork_types import MovieArtwork, TVArtwork, CollectionArtwork
from models.options import Options
from plex.plex_connector import PlexConnector
from plex.plex_uploader import PlexUploader
from plexapi.exceptions import NotFound
from utils import soup_utils
from utils.notifications import debug_me
from utils.utils import is_numeric, get_path_parts


class UploadProcessor:

    def __init__(self, plex: PlexConnector) -> None:
        self.plex: PlexConnector = plex
        self.options: Options = Options()
        self.config: Config = Config()
        self.config.load()
        self.docker: bool = os.getenv("RUNNING_IN_DOCKER") == "1"
        self.kometa: bool = self.options.kometa or globals.config.save_to_kometa
        self.staging: bool = self.kometa and (
            globals.config.stage_assets or self.options.stage)
        self.stage_specials: bool = globals.config.stage_specials
        self.stage_collections: bool = globals.config.stage_collections

    def set_options(self, options: Options) -> None:
        self.options = options

    def _season_exists_in_plex(self, tv_show, season_number: int) -> bool:
        """Check if a season exists in the Plex library."""
        return any(S.index == season_number for S in tv_show.seasons())

    def _episode_exists_in_plex(self, tv_show, season_number: int, episode_number: int) -> bool:
        """Check if an episode exists in the Plex library."""
        return (self._season_exists_in_plex(tv_show, season_number) and
                any(E.index == episode_number for E in tv_show.season(season_number).episodes()))

    def _should_process_season(self, tv_show, season_number: int, season_name: str) -> bool:
        """
        Determine if a season should be processed based on Plex availability and staging settings.

        Returns True if:
        - Season exists in Plex, OR
        - Staging is enabled for regular seasons (not specials), OR
        - Stage specials is enabled and this is a specials season (in Kometa mode)
        """
        is_specials = (season_name == SEASON_SPECIALS)

        # Season exists in Plex
        return (self._season_exists_in_plex(tv_show, season_number) or
                (self.staging and not is_specials) or
                (self.kometa and self.stage_specials and is_specials))

    def _should_process_episode(self, tv_show, season_number: int, episode_number: int, season_name: str) -> bool:
        """
        Determine if an episode should be processed based on Plex availability and staging settings.

        Returns True if:
        - Episode exists in Plex, OR
        - Staging is enabled (allows episodes not yet in Plex)
        """
        # Check if season should be processed first
        if not self._should_process_season(tv_show, season_number, season_name):
            return False

        # If episode exists in Plex, always process
        return (self._episode_exists_in_plex(tv_show, season_number, episode_number) or
                self.staging)

    def check_master_filters(self, check_filter: str, source: str) -> bool:
        master_filters = self.config.tpdb_filters if source == ScraperSource.THEPOSTERDB.value else self.config.mediux_filters
        return check_filter in master_filters if master_filters else True

    def process_collection_artwork(self, artwork: CollectionArtwork) -> list[Any]:

        collection_items, libraries = self.plex.find_collection(
            artwork["title"])

        if not collection_items:
            collection_items, libraries = self.plex.find_collection(
                artwork["title"].replace(" Collection", ""))

        results = []
        artwork_source = artwork["source"]
        description = f"{artwork["title"]} : {artwork["author"]}"
        filter_type = FilterType.COLLECTION_POSTER.value if artwork[
            "type"] == "collection poster" else FilterType.BACKGROUND.value
        artwork_type = "Poster" if artwork["type"] == "collection poster" else "Background"
        artwork_id = artwork_type[0]

        if collection_items:
            debug_me(f"Found collection '{artwork["title"]}' in {len(libraries)} libraries.",
                     "UploadProcessor/process_movie_artwork")
            for collection_item, library in zip(collection_items, libraries):
                if (self.options.has_no_filters() and self.check_master_filters(filter_type,
                                                                                artwork_source)) or self.options.has_filter(
                        filter_type):
                    if not self.options.is_excluded(artwork["id"]):
                        if self.options.kometa or globals.config.save_to_kometa:
                            asset_folder = collection_item.title
                            saver = KometaSaver(artwork_type, library)
                            saver.set_artwork(artwork)
                            base_dir = ("/temp" if self.options.temp else "/assets") if self.docker else getattr(
                                globals.config, "temp_dir" if self.options.temp else "kometa_base", None)
                            saver.dest_dir = os.path.join(
                                base_dir, library, asset_folder)
                            debug_me(f"Destination directory is {saver.dest_dir}",
                                     "UploadProcessor/process_collection_artwork")
                            saver.dest_file_name = artwork_type.lower()
                            saver.dest_file_ext = ".jpg"
                            saver.set_description(description)
                            saver.set_options(self.options)
                            result = saver.save_to_kometa()
                            results.append(result)
                        else:
                            uploader = PlexUploader(
                                collection_item, artwork_type, artwork_id)
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
                    raise NotProcessedByFilter(
                        f"{description} | {artwork_type} not processed due to {'requested' if not self.options.has_filter(filter_type) else artwork_source} filtering")
        elif self.kometa and self.stage_collections:
            # Stage collection artwork to Kometa even though collection doesn't exist in Plex
            # Save to all configured movie libraries
            movie_libraries = self.config.movie_library if isinstance(self.config.movie_library, list) else [self.config.movie_library]
            for library in movie_libraries:
                if (self.options.has_no_filters() and self.check_master_filters(filter_type,
                                                                                artwork_source)) or self.options.has_filter(
                        filter_type):
                    if not self.options.is_excluded(artwork["id"]):
                        asset_folder = artwork["title"]
                        saver = KometaSaver(artwork_type, library)
                        saver.set_artwork(artwork)
                        base_dir = ("/temp" if self.options.temp else "/assets") if self.docker else getattr(
                            globals.config, "temp_dir" if self.options.temp else "kometa_base", None)
                        saver.dest_dir = os.path.join(
                            base_dir, library, asset_folder)
                        debug_me(f"Staging collection to {saver.dest_dir}",
                                 "UploadProcessor/process_collection_artwork")
                        saver.dest_file_name = artwork_type.lower()
                        saver.dest_file_ext = ".jpg"
                        saver.set_description(description)
                        saver.set_options(self.options)
                        result = saver.save_to_kometa()
                        results.append(result)
                    else:
                        raise NotProcessedByExclusion(
                            f"{description} | Poster excluded")
                else:
                    raise NotProcessedByFilter(
                        f"{description} | {artwork_type} not processed due to {'requested' if not self.options.has_filter(filter_type) else artwork_source} filtering")
        else:
            raise CollectionNotFound(
                f'{description} | Collection not available on Plex')
        return results

    def process_movie_artwork(self, artwork: MovieArtwork) -> list[Any]:

        artwork["year"] = self.options.year if self.options.year else artwork["year"]

        # Since the TBDb scraper doesn't fetch the TMDb ID up front for each poster, we need to get it here
        if not artwork.get("tmdb_id") and artwork.get("source") == ScraperSource.THEPOSTERDB.value and artwork.get(
                "id") != "Upload":
            poster_id = artwork.get("id", None)
            poster_page_url = f"{TPDB_BASE_URL}/poster/{poster_id}"
            debug_me(
                f"Fetching TMDb ID from '{poster_page_url}'", "UploadProcessor/process_movie_artwork")
            poster_page_soup = soup_utils.cook_soup(poster_page_url)
            artwork["tmdb_id"] = int(poster_page_soup.find(
                'div', {"data-media-id": True})['data-media-id'])

        movie_items, libraries = self.plex.find_in_library("movie", artwork)

        results = []
        artwork_source = artwork["source"]
        description = f"{artwork['title']} ({artwork['year']}) : {artwork['author']}"
        filter_type = FilterType.MOVIE_POSTER.value if artwork.get(
            "type") == "poster" else FilterType.BACKGROUND.value
        artwork_type = "Poster" if artwork.get(
            "type") == "poster" else "Background"
        artwork_id = artwork_type[0]

        if movie_items:
            debug_me(f"Found TMDb ID '{artwork.get('tmdb_id')}' in {len(libraries)} libraries.",
                     "UploadProcessor/process_movie_artwork")
            for movie_item, library in zip(movie_items, libraries):
                # Use the actual movie title from Plex in case it differs from the artwork title (if it's a foreign title, etc.)
                desc = description.replace(artwork["title"], movie_item.title) if movie_item.title != artwork[
                    "title"] else description
                if (self.options.has_no_filters() and self.check_master_filters(filter_type,
                                                                                artwork_source)) or self.options.has_filter(
                        filter_type):
                    if not self.options.is_excluded(artwork["id"]):
                        if self.options.kometa or globals.config.save_to_kometa:
                            item_path = movie_item.media[0].parts[0].file
                            path_parts = get_path_parts(item_path)
                            asset_folder = path_parts[-2]
                            saver = KometaSaver(artwork_type, library)
                            saver.set_artwork(artwork)
                            base_dir = ("/temp" if self.options.temp else "/assets") if self.docker else getattr(
                                globals.config, "temp_dir" if self.options.temp else "kometa_base", None)
                            saver.dest_dir = os.path.join(
                                base_dir, library, asset_folder)
                            debug_me(f"Destination directory is {saver.dest_dir}",
                                     "UploadProcessor/process_movie_artwork")
                            saver.dest_file_name = artwork_type.lower()
                            saver.dest_file_ext = ".jpg"
                            saver.set_description(desc)
                            saver.set_options(self.options)
                            result = saver.save_to_kometa()
                            results.append(result)
                        else:
                            uploader = PlexUploader(
                                movie_item, artwork_type, artwork_id)
                            uploader.set_artwork(artwork)
                            uploader.track_artwork_ids = self.config.track_artwork_ids
                            uploader.reset_overlay = self.config.reset_overlay
                            uploader.set_description(desc)
                            uploader.set_options(self.options)
                            result = uploader.upload_to_plex()
                            results.append(result)
                    else:
                        raise NotProcessedByExclusion(
                            f"{desc} | {artwork_type} Poster excluded")
                else:
                    raise NotProcessedByFilter(
                        f"{desc} | {artwork_type} filtered by {'request' if not self.options.has_filter(filter_type) else artwork_source}")
        else:
            raise MovieNotFound(f'{description} | Movie not available on Plex')
        return results

    def process_tv_artwork(self, artwork: TVArtwork) -> list[Any]:

        description = "Target media"
        upload_target = None
        artwork_type = None
        filter_type = None
        artwork_id = None
        artwork_source = artwork["source"]
        results = []

        season = artwork.get('season')
        if is_numeric(season) and season == 0:
            season = SEASON_SPECIALS
        else:
            season = f"Season {artwork['season']:02}"
        #
        if is_numeric(artwork['season']) and is_numeric(artwork['episode']):
            description = f"{artwork['title']} ({artwork['year']}) : {artwork['author']} : {season}, Episode {artwork['episode']:02}"
        elif (artwork['episode'] is None or artwork['episode'] == EPISODE_COVER) and is_numeric(artwork['season']):
            description = f"{artwork['title']} ({artwork['year']}) : {artwork['author']} : {season}"
        elif artwork['season'] is None or artwork["season"] == SEASON_COVER or artwork["season"] == SEASON_BACKDROP:
            description = f"{artwork['title']} ({artwork['year']}) : {artwork['author']}"

        artwork["year"] = self.options.year if self.options.year else artwork["year"]

        # Since the TBDb scraper doesn't fetch the TMDb ID up front for each poster, we need to get it here
        if not artwork.get("tmdb_id") and artwork.get("source") == ScraperSource.THEPOSTERDB.value and artwork.get(
                "id") != "Upload":
            poster_id = artwork.get("id", None)
            poster_page_url = f"{TPDB_BASE_URL}/poster/{poster_id}"
            debug_me(
                f"Fetching TMDb ID from {poster_page_url}", "UploadProcessor/process_movie_artwork")
            poster_page_soup = soup_utils.cook_soup(poster_page_url)
            artwork["tmdb_id"] = int(poster_page_soup.find(
                'div', {"data-media-id": True})['data-media-id'])

        tv_show_items, libraries = self.plex.find_in_library("tv", artwork)

        if not tv_show_items:
            raise ShowNotFound(f"{description} | Show not available on Plex")
        debug_me(f"Found TMDb ID '{artwork.get('tmdb_id')}' in {len(libraries)} libraries.",
                 "UploadProcessor/process_movie_artwork")
        for tv_show, library in zip(tv_show_items, libraries):
            # Use the actual TV show title from Plex in case it differs from the artwork title (if it's a foreign title, etc.)
            desc = description.replace(artwork["title"], tv_show.title.split(' (')[0]) if tv_show.title.split(' (')[
                0] != artwork[
                "title"] else description
            item_path = tv_show.seasons()[0].episodes()[
                0].media[0].parts[0].file
            path_parts = get_path_parts(item_path)
            asset_folder = path_parts[-3] if path_parts[-2].lower().startswith("season") or path_parts[
                -2].lower().startswith("specials") else path_parts[-2]
            try:
                if artwork["season"] == SEASON_COVER:
                    upload_target = tv_show
                    artwork_id = "C"
                    artwork_type = "Show cover"
                    file_name = "poster"
                    filter_type = FilterType.SHOW_COVER.value
                elif artwork["season"] == SEASON_BACKDROP:
                    upload_target = tv_show
                    artwork_id = "B"
                    artwork_type = "Background"
                    file_name = "background"
                    filter_type = FilterType.BACKGROUND.value
                elif artwork["season"] >= 0:
                    if artwork["episode"] == EPISODE_COVER or artwork["episode"] is None:
                        # Season cover artwork
                        if self._should_process_season(tv_show, artwork["season"], season):
                            debug_me(f"Staging is {'enabled' if self.staging else 'disabled'}.",
                                     "UploadProcessor/process_tv_artwork")
                            if not self.kometa:
                                upload_target = tv_show.season(artwork["season"])
                            artwork_id = "S"
                            artwork_type = "Season cover"
                            file_name = f"Season{artwork["season"]:02}"
                            filter_type = FilterType.SEASON_COVER.value
                        else:
                            result = f"⚠️ {desc} | {season} not available in {library}"
                            results.append(result)
                            continue
                    elif artwork["episode"] >= 0:
                        # Episode title card artwork
                        if self._should_process_season(tv_show, artwork["season"], season):
                            # Season is processable, check episode
                            if self._episode_exists_in_plex(tv_show, artwork["season"], artwork["episode"]) or self.staging:
                                if not self.kometa:
                                    upload_target = tv_show.season(artwork["season"]).episode(artwork["episode"])
                                artwork_id = "E"
                                artwork_type = "Title card"
                                file_name = f"S{artwork["season"]:02}E{artwork["episode"]:02}"
                                filter_type = FilterType.TITLE_CARD.value
                            else:
                                result = f"⚠️ {desc} | {season}, Episode {artwork["episode"]:02} not available in {library}"
                                results.append(result)
                                continue
                        else:
                            # Season is not processable
                            result = f"⚠️ {desc} | {season} not available in {library}"
                            results.append(result)
                            continue

            except (AttributeError, KeyError, NotFound) as e:
                raise ShowNotFound(
                    f"{desc} | Not available on Plex in {library}: {e}") from e

            try:
                if upload_target or (self.options.kometa or globals.config.save_to_kometa):
                    if (self.options.has_no_filters() and self.check_master_filters(filter_type,
                                                                                    artwork_source)) or self.options.has_filter(
                            filter_type):
                        # Pass season/episode info for TV show exclusion checks
                        season_num = artwork['season'] if isinstance(
                            artwork['season'], int) else None
                        episode_num = artwork['episode'] if isinstance(
                            artwork['episode'], int) else None
                        if not self.options.is_excluded(artwork["id"], season_num, episode_num):
                            if self.kometa:
                                saver = KometaSaver(artwork_type, library)
                                saver.set_artwork(artwork)
                                base_dir = (
                                    "/temp" if self.options.temp else "/assets") if self.docker else getattr(
                                    globals.config, "temp_dir" if self.options.temp else "kometa_base", None)
                                saver.dest_dir = os.path.join(
                                    base_dir, library, asset_folder)
                                debug_me(f"Destination directory is {saver.dest_dir}",
                                         "UploadProcessor/process_tv_artwork")
                                saver.dest_file_name = file_name
                                saver.dest_file_ext = ".jpg"
                                saver.set_description(desc)
                                saver.set_options(self.options)
                                result = saver.save_to_kometa()
                                results.append(result)
                            else:
                                uploader = PlexUploader(
                                    upload_target, artwork_type, artwork_id)
                                uploader.set_artwork(artwork)
                                uploader.track_artwork_ids = self.config.track_artwork_ids
                                uploader.reset_overlay = self.config.reset_overlay
                                uploader.set_description(desc)
                                uploader.set_options(self.options)
                                result = uploader.upload_to_plex()
                                results.append(result)
                        else:
                            raise NotProcessedByExclusion(
                                f"{desc} | {artwork_type} excluded")
                    else:
                        raise NotProcessedByFilter(
                            f"{desc} | {artwork_type} not processed due to {'requested' if not self.options.has_filter(filter_type) else artwork_source} filtering")
            except Exception:
                raise

        return results
