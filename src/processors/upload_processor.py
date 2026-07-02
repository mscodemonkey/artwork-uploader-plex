import os
from typing import Any, Optional, TYPE_CHECKING, Union

from core import globals
from core.config import Config
from core.constants import (
    SEASON_COVER, SEASON_BACKDROP, SEASON_SPECIALS, SEASON_SQUARE_ART,
    EPISODE_COVER, TPDB_BASE_URL
)
from core.enums import FilterType, ScraperSource
from core.exceptions import CollectionNotFound, MovieNotFound, NotProcessedByFilter, ShowNotFound, \
    NotProcessedByExclusion
from kometa.kometa_saver import KometaSaver
from models.artwork_types import AnyArtwork, MovieArtwork, TVArtwork, CollectionArtwork
from models.options import Options
from plex.plex_connector import PlexConnector
from plex.plex_uploader import PlexUploader
from plexapi.exceptions import NotFound
from utils import soup_utils
from utils.notifications import debug_me
from utils.utils import is_numeric, get_path_parts

if TYPE_CHECKING:
    from services.arr_service import ArrService


class UploadProcessor:

    def __init__(self, plex: PlexConnector, arr: Optional["ArrService"] = None) -> None:
        self.plex: PlexConnector = plex
        self.options: Options = Options()
        self.config: Config = Config()
        self.config.load()
        self.stage_specials: bool = globals.config.stage_specials
        self.stage_collections: bool = globals.config.stage_collections
        self.arr: Optional["ArrService"] = arr if arr is not None else globals.arr
        self._sonarr_series_cache: dict = {}
        self._recompute_options_dependent_state()

    def _recompute_options_dependent_state(self) -> None:
        """Recompute flags derived from self.options; must run whenever options change."""
        self.kometa: bool = self.options.kometa or globals.config.save_to_kometa
        self.staging: bool = self.kometa and (
            globals.config.stage_assets or self.options.stage)
        self._arr_movie_fallback: bool = bool(
            self.kometa and self.arr and self.arr.movie_fallback_enabled)
        self._arr_tv_fallback: bool = bool(
            self.kometa and self.arr and self.arr.tv_fallback_enabled)

    def set_options(self, options: Options) -> None:
        self.options = options
        self._recompute_options_dependent_state()

    def _season_exists_in_plex(self, tv_show, season_number: int) -> bool:
        """Check if a season exists in the Plex library."""
        return any(S.index == season_number for S in tv_show.seasons())

    def _episode_exists_in_plex(self, tv_show, season_number: int, episode_number: int) -> bool:
        """Check if an episode exists in the Plex library."""
        return (self._season_exists_in_plex(tv_show, season_number) and
                any(E.index == episode_number for E in tv_show.season(season_number).episodes()))

    def _should_process_season(
            self, tv_show, season_number: int, season_name: str,
            sonarr_seasons: Optional[set] = None) -> bool:
        """
        Determine if a season should be processed based on Plex availability and staging settings.

        Returns True if:
        - Season exists in Plex, OR
        - Staging is enabled for regular seasons (not specials), OR
        - Stage specials is enabled and this is a specials season (in Kometa mode), OR
        - Sonarr knows about this season and it's not a specials season (or specials staging is on)
          (Kometa mode only - lets a season be pre-seeded before Plex has it)
        """
        is_specials = (season_name == SEASON_SPECIALS)

        # Season exists in Plex
        return (self._season_exists_in_plex(tv_show, season_number) or
                (self.staging and not is_specials) or
                (self.kometa and self.stage_specials and is_specials) or
                (self.kometa and sonarr_seasons is not None and season_number in sonarr_seasons and
                 (not is_specials or self.stage_specials)))

    def _should_process_episode(
            self, tv_show, season_number: int, episode_number: int, season_name: str,
            sonarr_seasons: Optional[set] = None) -> bool:
        """
        Determine if an episode should be processed based on Plex availability and staging settings.

        Returns True if:
        - Episode exists in Plex, OR
        - Staging is enabled (allows episodes not yet in Plex), OR
        - Sonarr knows about the episode's season (Kometa mode only)
        """
        # Check if season should be processed first
        if not self._should_process_season(tv_show, season_number, season_name, sonarr_seasons):
            return False

        # If episode exists in Plex, always process
        return (self._episode_exists_in_plex(tv_show, season_number, episode_number) or
                self.staging or
                (sonarr_seasons is not None and season_number in sonarr_seasons))

    def _find_sonarr_series(self, artwork: TVArtwork):
        """Looks up (and memoizes) the Sonarr series for this artwork's title/year/tmdb_id."""
        cache_key = (artwork.get("tmdb_id"), artwork.get("title"), artwork.get("year"))
        if cache_key not in self._sonarr_series_cache:
            self._sonarr_series_cache[cache_key] = self.arr.sonarr.find_series(
                artwork.get("tmdb_id"), artwork.get("title"), artwork.get("year"))
        return self._sonarr_series_cache[cache_key]

    def _get_sonarr_seasons_if_needed(self, tv_show, artwork: TVArtwork, season_number: int) -> Optional[set]:
        """
        Fetches Sonarr's known season numbers for this show, but only when the season is
        missing in Plex and the arr TV fallback is enabled - avoids an HTTP call on the happy path.
        """
        if not self._arr_tv_fallback or self._season_exists_in_plex(tv_show, season_number):
            return None
        arr_series = self._find_sonarr_series(artwork)
        return arr_series.season_numbers if arr_series else None

    def _tv_artwork_mapping(self, artwork: TVArtwork) -> tuple[str, str, str, str]:
        """Maps TV artwork to (artwork_id, artwork_type, file_name, filter_type)."""
        if artwork["season"] == SEASON_COVER:
            return "C", "Show cover", "poster", FilterType.SHOW_COVER.value
        if artwork["season"] == SEASON_BACKDROP:
            return "B", "Background", "background", FilterType.BACKGROUND.value
        if artwork["season"] == SEASON_SQUARE_ART:
            return "SA", "Square art", "square", FilterType.SQUARE_ART.value
        if artwork["episode"] == EPISODE_COVER or artwork["episode"] is None:
            return "S", "Season cover", f"Season{artwork['season']:02}", FilterType.SEASON_COVER.value
        return "E", "Title card", f"S{artwork['season']:02}E{artwork['episode']:02}", FilterType.TITLE_CARD.value

    def _save_kometa_asset(
            self, artwork: AnyArtwork, library: str, asset_folder: str, file_name: str,
            artwork_type: str, description: str) -> str:
        saver = KometaSaver(artwork_type, library)
        saver.set_artwork(artwork)
        dest_dir = self._get_kometa_dest_dir(library, asset_folder)
        saver.dest_dir = dest_dir
        debug_me(f"Destination directory is {saver.dest_dir}",
                 "UploadProcessor/_save_kometa_asset")
        saver.dest_file_name = file_name
        saver.dest_file_ext = ".jpg"
        saver.set_description(description)
        saver.set_options(self.options)
        return saver.save_to_kometa()

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
        description = f"{artwork['title']} : {artwork['author']}"
        filter_type = FilterType.COLLECTION_POSTER.value if artwork[
            "type"] == FilterType.COLLECTION_POSTER.value else FilterType.BACKGROUND.value
        artwork_type = "Poster" if artwork["type"] == FilterType.COLLECTION_POSTER.value else "Background"
        artwork_id = artwork_type[0]

        if collection_items:
            debug_me(f"Found collection '{artwork['title']}' in {len(libraries)} libraries.",
                     "UploadProcessor/process_movie_artwork")
            for collection_item, library in zip(collection_items, libraries):
                if (self.options.has_no_filters() and self.check_master_filters(filter_type,
                                                                                artwork_source)) or self.options.has_filter(
                        filter_type):
                    if not self.options.is_excluded(artwork["id"]):
                        if self.options.kometa or globals.config.save_to_kometa:
                            asset_folder = collection_item.title
                            result = self._save_kometa_asset(
                                artwork, library, asset_folder, artwork_type.lower(), artwork_type, description)
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
                        result = self._save_kometa_asset(
                            artwork, library, asset_folder, artwork_type.lower(), artwork_type, description)
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

    def _fetch_tpdb_tmdb_id(self, artwork: Union[MovieArtwork, TVArtwork], context: str) -> None:
        # Since the TPDb scraper doesn't fetch the TMDb ID up front for each poster, we need to get it here
        if artwork.get("tmdb_id") or artwork.get("source") != ScraperSource.THEPOSTERDB.value or artwork.get(
                "id") == "Upload":
            return
        poster_id = artwork.get("id", None)
        poster_page_url = f"{TPDB_BASE_URL}/poster/{poster_id}"
        debug_me(f"Fetching TMDb ID from '{poster_page_url}'", context)
        poster_page_soup = soup_utils.cook_soup(poster_page_url)
        try:
            artwork["tmdb_id"] = int(poster_page_soup.find(
                'div', {"data-media-id": True})['data-media-id'])
        except (KeyError, TypeError, ValueError) as e:
            # find_in_library falls back to a title/year search when tmdb_id is unset
            debug_me(f"Failed to extract TMDb ID from poster page, relying on title/year lookup. Error was: {e}",
                     context)
            artwork["tmdb_id"] = None

    def process_movie_artwork(self, artwork: MovieArtwork) -> list[Any]:

        artwork["year"] = self.options.year if self.options.year else artwork["year"]

        self._fetch_tpdb_tmdb_id(artwork, "UploadProcessor/process_movie_artwork")

        movie_items, libraries = self.plex.find_in_library("movie", artwork)

        results = []
        artwork_source = artwork["source"]
        description = f"{artwork['title']} ({artwork['year']}) : {artwork['author']}"
        if artwork.get("type") == FilterType.MOVIE_POSTER.value:
            filter_type = FilterType.MOVIE_POSTER.value
            artwork_type = "Poster"
        elif artwork.get("type") == FilterType.SQUARE_ART.value:
            filter_type = FilterType.SQUARE_ART.value
            artwork_type = "Square art"
        else:
            filter_type = FilterType.BACKGROUND.value
            artwork_type = "Background"
        artwork_id = "SA" if artwork.get(
            "type") == FilterType.SQUARE_ART.value else artwork_type[0]

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
                            file_name = "square" if artwork.get(
                                "type") == FilterType.SQUARE_ART.value else artwork_type.lower()
                            result = self._save_kometa_asset(
                                artwork, library, asset_folder, file_name, artwork_type, desc)
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
        elif self._arr_movie_fallback:
            arr_movie = self.arr.radarr.find_movie(
                artwork.get("tmdb_id"), artwork["title"], artwork["year"])
            if not arr_movie:
                raise MovieNotFound(
                    f"{description} | Movie not available on Plex or Radarr")
            if (self.options.has_no_filters() and self.check_master_filters(filter_type,
                                                                            artwork_source)) or self.options.has_filter(
                    filter_type):
                if not self.options.is_excluded(artwork["id"]):
                    library = self.config.resolve_arr_library(arr_movie.root_folder_path, "movie")
                    file_name = "square" if artwork.get(
                        "type") == FilterType.SQUARE_ART.value else artwork_type.lower()
                    result = self._save_kometa_asset(
                        artwork, library, arr_movie.folder_name, file_name, artwork_type,
                        f"{description} • pre-seeded via Radarr")
                    results.append(result)
                else:
                    raise NotProcessedByExclusion(
                        f"{description} | {artwork_type} Poster excluded")
            else:
                raise NotProcessedByFilter(
                    f"{description} | {artwork_type} filtered by {'request' if not self.options.has_filter(filter_type) else artwork_source}")
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
        elif artwork['season'] is None or artwork["season"] == SEASON_COVER or artwork["season"] == SEASON_BACKDROP or artwork["season"] == SEASON_SQUARE_ART:
            description = f"{artwork['title']} ({artwork['year']}) : {artwork['author']}"

        artwork["year"] = self.options.year if self.options.year else artwork["year"]

        self._fetch_tpdb_tmdb_id(artwork, "UploadProcessor/process_tv_artwork")

        tv_show_items, libraries = self.plex.find_in_library("tv", artwork)

        if not tv_show_items:
            if self._arr_tv_fallback:
                return self._preseed_tv_artwork(artwork, description, season, artwork_source)
            raise ShowNotFound(f"{description} | Show not available on Plex")
        debug_me(f"Found TMDb ID '{artwork.get('tmdb_id')}' in {len(libraries)} libraries.",
                 "UploadProcessor/process_tv_artwork")
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
                if artwork["season"] in (SEASON_COVER, SEASON_BACKDROP, SEASON_SQUARE_ART):
                    upload_target = tv_show
                    artwork_id, artwork_type, file_name, filter_type = self._tv_artwork_mapping(artwork)
                elif artwork["season"] >= 0:
                    if artwork["episode"] == EPISODE_COVER or artwork["episode"] is None:
                        # Season cover artwork
                        sonarr_seasons = self._get_sonarr_seasons_if_needed(tv_show, artwork, artwork["season"])
                        if self._should_process_season(tv_show, artwork["season"], season, sonarr_seasons):
                            debug_me(f"Staging is {'enabled' if self.staging else 'disabled'}.",
                                     "UploadProcessor/process_tv_artwork")
                            if not self.kometa:
                                upload_target = tv_show.season(artwork["season"])
                            artwork_id, artwork_type, file_name, filter_type = self._tv_artwork_mapping(artwork)
                            if sonarr_seasons is not None and artwork["season"] in sonarr_seasons:
                                desc = f"{desc} • pre-seeded via Sonarr"
                        else:
                            result = f"⚠️ {desc} | {season} not available in {library}"
                            results.append(result)
                            continue
                    elif artwork["episode"] >= 0:
                        # Episode title card artwork
                        sonarr_seasons = self._get_sonarr_seasons_if_needed(tv_show, artwork, artwork["season"])
                        if self._should_process_season(tv_show, artwork["season"], season, sonarr_seasons):
                            # Season is processable, check episode
                            via_sonarr = sonarr_seasons is not None and artwork["season"] in sonarr_seasons
                            if self._episode_exists_in_plex(tv_show, artwork["season"], artwork["episode"]) or self.staging or via_sonarr:
                                if not self.kometa:
                                    upload_target = tv_show.season(artwork["season"]).episode(artwork["episode"])
                                artwork_id, artwork_type, file_name, filter_type = self._tv_artwork_mapping(artwork)
                                if via_sonarr:
                                    desc = f"{desc} • pre-seeded via Sonarr"
                            else:
                                result = f"⚠️ {desc} | {season}, Episode {artwork['episode']:02} not available in {library}"
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
                                result = self._save_kometa_asset(
                                    artwork, library, asset_folder, file_name, artwork_type, desc)
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

    def _preseed_tv_artwork(self, artwork: TVArtwork, description: str, season: str, artwork_source: str) -> list[Any]:
        """
        Pre-seeds Kometa artwork for a show that isn't in Plex yet, using Sonarr to
        locate the show's asset folder and confirm which seasons it knows about.
        """
        results: list[Any] = []

        arr_series = self._find_sonarr_series(artwork)
        if not arr_series:
            raise ShowNotFound(
                f"{description} | Show not available on Plex or Sonarr")

        if artwork["season"] not in (SEASON_COVER, SEASON_BACKDROP, SEASON_SQUARE_ART):
            is_specials = (season == SEASON_SPECIALS)
            if artwork["season"] not in arr_series.season_numbers or (is_specials and not self.stage_specials):
                result = f"⚠️ {description} | {season} not known to Sonarr"
                results.append(result)
                return results

        _, artwork_type, file_name, filter_type = self._tv_artwork_mapping(artwork)

        if (self.options.has_no_filters() and self.check_master_filters(filter_type,
                                                                        artwork_source)) or self.options.has_filter(
                filter_type):
            season_num = artwork['season'] if isinstance(
                artwork['season'], int) else None
            episode_num = artwork['episode'] if isinstance(
                artwork['episode'], int) else None
            if not self.options.is_excluded(artwork["id"], season_num, episode_num):
                library = self.config.resolve_arr_library(arr_series.root_folder_path, "tv")
                result = self._save_kometa_asset(
                    artwork, library, arr_series.folder_name, file_name, artwork_type,
                    f"{description} • pre-seeded via Sonarr")
                results.append(result)
            else:
                raise NotProcessedByExclusion(
                    f"{description} | {artwork_type} excluded")
        else:
            raise NotProcessedByFilter(
                f"{description} | {artwork_type} not processed due to {'requested' if not self.options.has_filter(filter_type) else artwork_source} filtering")

        return results

    def _get_kometa_dest_dir(self, library: str, asset_folder: str) -> str:
        """Constructs the destination directory path for Kometa assets."""
        config_attr = "temp_dir" if self.options.temp else "kometa_base"
        base_dir = getattr(globals.config, config_attr, "")
        if not base_dir:
            mode = "temporary" if self.options.temp else "Kometa base"
            raise ValueError(
                f"{mode} directory is not configured. "
                f"Please set '{config_attr}' in the application configuration before saving assets to Kometa."
            )
        library_dir = globals.config.resolve_library_directory(library)
        return os.path.join(base_dir, library_dir, asset_folder)
