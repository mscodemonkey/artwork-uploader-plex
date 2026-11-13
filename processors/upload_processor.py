import os
from typing import Optional, Literal
from core.config import Config
from core.exceptions import CollectionNotFound, CollectionsNotSupported, MovieNotFound, ShowNotFound, PlexConnectorException
from core.enums import ScraperSource, MediaType
from core.exceptions import ScraperException
from core.constants import ARTWORK_ID_MAP, ARTWORK_TYPE_MAP, ARTWORK_FILENAME_MAP, KOMETA_OVERLAY_LABEL, DOCKER_KOMETA_ASSETS_PATH, DOCKER_KOMETA_TEMP_PATH
from models.options import Options
from plex.plex_connector import PlexConnector
from plex.plex_uploader import PlexUploader
from plexapi.exceptions import NotFound
from kometa.kometa_saver import KometaSaver
from utils import soup_utils
from utils.utils import is_numeric, get_path_parts, normalize_path, title_cleaner
from models.artwork_types import MovieArtwork, TVArtwork, CollectionArtwork
from models.callbacks import ProcessingCallbacks
from core import globals

class UploadProcessor:

    def __init__(self, plex: PlexConnector, callbacks: Optional[ProcessingCallbacks]) -> None:
        self.plex: PlexConnector = plex
        self.callbacks: ProcessingCallbacks = callbacks
        self.options: Options = Options()
        self.config: Config = Config()
        self.config.load()
        self._match_confirm_cache: dict = {}
        self.artist_assets: Optional[dict] = None  # {md5(asset url): asset id} for the artist being processed


    def set_options(self, options: Options) -> None:
        self.options = options
        self.local_assets: bool = self.options.local_assets or globals.config.plex_local_assets
        self.kometa: bool = self.options.kometa or globals.config.save_to_kometa
        self.kometa_auto_run: bool = globals.config.kometa_auto_run and not self.options.temp
        self.skip_locked: bool = self.options.skip_locked or globals.config.skip_locked_artwork
        requested_artist_updates: bool = self.options.allow_artist_updates or globals.config.allow_artist_updates
        # Artist updates read the artwork ID labels to tell our own artwork from a hand-set custom.
        # Without track_artwork_ids there are no fresh labels to read, and labels left behind by an
        # earlier tracked run would let a locked field be replaced on stale information.
        self.allow_artist_updates: bool = requested_artist_updates and self.config.track_artwork_ids
        if requested_artist_updates and not self.config.track_artwork_ids:
            self.callbacks.debug("allow_artist_updates has no effect while track_artwork_ids is off - without "
                     "artwork IDs there's no way to tell artwork we applied from artwork set by "
                     "hand, so locked items are all left alone.")

    def _resolve_tmdb_id(self, artwork, description: str, kind: Literal[MediaType.TV_SHOW, MediaType.MOVIE]) -> bool:
        """
        Resolve the TMDb ID for a TPDb artwork item before matching it to the library.

        With local_library_matching enabled (the default), the title and year from the scrape are
        matched against an in-memory index of the Plex libraries first, so items that aren't in the
        library are skipped without any web request, and items that are get their TMDb ID from
        Plex's own guids. Only an ambiguous local match falls back to fetching the poster page.

        Returns True when the artwork was matched locally - the caller then attaches a
        confirm_match hook so the poster page is still checked before anything is written.
        """
        if artwork.get("tmdb_id") or artwork.get("source") != ScraperSource.THEPOSTERDB.value or artwork.get("id") == "Upload":
            return False

        if self.config.local_library_matching and artwork.get("title"):
            self.plex._initialize_index()
            status, match = self.plex._index.lookup(artwork.get("title"), artwork.get("year"), kind)
            if status == "not_found":
                if kind == MediaType.MOVIE:
                    raise MovieNotFound(f'{description} | Movie not available on Plex')
                raise ShowNotFound(f'{description} | Show not available on Plex')
            if status == "matched":
                tmdb_id = match.get("tmdb_id")
                self.callbacks.debug(f"Matched '{artwork.get('title')} ({artwork.get('year')})' locally as TMDb ID '{tmdb_id}'")
                artwork["tmdb_id"] = tmdb_id
                return True
            self.callbacks.debug(f"'{artwork.get('title')} ({artwork.get('year')})' is ambiguous locally, fetching the poster page")

        self._fetch_tmdb_id_from_tpdb(artwork, description)
        return False

    def _fetch_tmdb_id_from_tpdb(self, artwork, description: str) -> None:
        """Fetch the poster page from ThePosterDB to read its TMDb ID (data-media-id), falling back
           to a local Plex title/year search if the page doesn't expose one."""
        poster_id = artwork.get("id", None)
        poster_page_url = f"https://theposterdb.com/poster/{poster_id}"
        self.callbacks.debug(f"Fetching TMDb ID from '{poster_page_url}'")
        try:
            poster_page_soup = soup_utils.cook_soup(poster_page_url)
        except ScraperException as e:
            self.callbacks.debug(f"Unable to fetch TMDb ID due to error: {str(e)}")
            raise ScraperException(f"{description} | {str(e)}") from None
        try:
            artwork["tmdb_id"] = int(poster_page_soup.find('div', {"data-media-id": True})['data-media-id'])
        except (KeyError, TypeError, ValueError) as e:
            self.callbacks.debug(f"Failed to extract TMDb ID from poster page, trying another way. Error was: {e}")
            _, artwork["tmdb_id"], _, _ = self.plex.movie_or_show(artwork.get("title"), artwork.get("year"))
            self.callbacks.debug(f"Found TMDb ID '{artwork['tmdb_id']}' for '{artwork.get('title')}' using Plex search.")

    def _artwork_matches_item(self, artwork, plex_item, kind: Literal[MediaType.TV_SHOW, MediaType.MOVIE]) -> bool:
        """
        Called by the uploader/saver just before artwork is actually written, and only for
        locally-matched items: fetches the poster page once (cached per title) and checks the
        TPDb media id against the matched Plex item's guids, so a title-and-year match can never
        write another title's artwork. Skips, locked items and items not in the library never
        trigger this request.
        """
        cache_key = (kind, artwork.get("title"), artwork.get("year"), artwork.get("tmdb_id"))
        cached = self._match_confirm_cache.get(cache_key)
        if cached is not None:
            return cached
        poster_page_url = f"https://theposterdb.com/poster/{artwork.get('id')}"
        self.callbacks.debug(f"Confirming local match for '{artwork.get('title')}' from '{poster_page_url}'")
        try:
            poster_page_soup = soup_utils.cook_soup(poster_page_url)
        except ScraperException:
            raise
        try:
            tpdb_tmdb_id = int(poster_page_soup.find('div', {"data-media-id": True})['data-media-id'])
            matches = any(guid.id == f"tmdb://{tpdb_tmdb_id}" for guid in plex_item.guids)
        except (KeyError, TypeError, ValueError):
            matches = True  # No media id on the page - trust the local title and year match, same as the existing Plex-search fallback
        self._match_confirm_cache[cache_key] = matches
        return matches

    def process_collection_artwork(self, artwork: CollectionArtwork) -> Optional[str]:

        result = None
        description = f"{artwork['title']} • {artwork['author']}"
        artwork_type = ARTWORK_TYPE_MAP.get(artwork.get('file_type'))
        artwork_id = ARTWORK_ID_MAP.get(artwork.get('file_type'))

        if self.local_assets:
            raise CollectionsNotSupported(f'{description} | {artwork_type} not processed (not supported in Plex local assets mode)')
        
        try:
            collection_items, libraries = self.plex.find_collection(artwork['title'])
            if not collection_items:
                collection_items, libraries = self.plex.find_collection(artwork['title'], fuzzy=True)

        except PlexConnectorException as e:
            raise PlexConnectorException(f"Error searching Plex for {artwork['title']}")
        except Exception as e:
            raise Exception from e

        if collection_items:
            self.callbacks.debug(f"Found collection '{artwork['title']}' in {len(libraries)} libraries.")
            for collection_item, library in zip(collection_items, libraries):
                artwork["library"] = library
                artwork["media_type"] = MediaType.COLLECTION.value
                if hasattr(collection_item, "ratingKey"):
                    artwork["ratingKey"] = collection_item.ratingKey
                if self.kometa:
                    asset_folder = collection_item.title.replace("/", "").replace(":", "")
                    saver = KometaSaver(artwork_type, library)
                    saver.download_timeout = self.config.kometa_download_timeout
                    saver.retry_attempts = self.config.upload_retry_attempts
                    saver.retry_backoff = self.config.upload_retry_backoff_seconds
                    saver.set_artwork(artwork)
                    base_dir = (DOCKER_KOMETA_TEMP_PATH if self.options.temp else DOCKER_KOMETA_ASSETS_PATH) if globals.docker else getattr(globals.config, "temp_dir" if self.options.temp else "kometa_base", None)
                    saver.dest_dir = os.path.join(base_dir, library, asset_folder)
                    self.callbacks.debug(f"Destination directory is {saver.dest_dir}")
                    saver.dest_file_name = ARTWORK_FILENAME_MAP.get(artwork.get('file_type'), 'poster')
                    saver.dest_file_ext = ".jpg"
                    saver.set_description(description)
                    saver.set_options(self.options)
                    result = saver.save_to_kometa()
                    self.callbacks.log(message=result)
                    self.callbacks.record_result(result=result, artwork=artwork if self.kometa_auto_run else None)
                else:
                    uploader = PlexUploader(collection_item, artwork_type, artwork_id)
                    uploader.set_artwork(artwork)
                    uploader.track_artwork_ids = self.config.track_artwork_ids
                    uploader.reset_overlay = self.config.reset_overlay
                    uploader.skip_locked = self.skip_locked
                    uploader.allow_artist_updates = self.allow_artist_updates
                    uploader.artist_assets = self.artist_assets
                    uploader.retry_attempts = self.config.upload_retry_attempts
                    uploader.retry_backoff = self.config.upload_retry_backoff_seconds
                    uploader.set_description(description)
                    uploader.set_options(self.options)
                    result = uploader.upload_to_plex()
                    self.callbacks.log(message=result)
                    self.callbacks.record_result(result=result)
        else:
            raise CollectionNotFound(f'{description} | {artwork_type} not processed (Collection not available on Plex)')
        # return results

    def process_movie_artwork(self, artwork: MovieArtwork) -> Optional[str]:

        artwork['year'] = self.options.year if self.options.year else artwork['year']
        
        result = None
        description = f"{artwork['title']} ({artwork['year']}) • {artwork['author']}"
        artwork_type = ARTWORK_TYPE_MAP.get(artwork.get('file_type'))
        artwork_id = ARTWORK_ID_MAP.get(artwork.get('file_type'))

        # Since the TPDb scraper doesn't fetch the TMDb ID up front for each poster, we resolve it here
        locally_matched = self._resolve_tmdb_id(artwork, description, MediaType.MOVIE)

        try:
            movie_items, libraries = self.plex.find_in_library(MediaType.MOVIE, artwork)
        except PlexConnectorException as e:
            raise PlexConnectorException(str(e))
        except Exception as e:
            raise Exception from e

        if movie_items:
            self.callbacks.debug(f"Found TMDb ID '{artwork.get('tmdb_id')}' in {len(libraries)} libraries.")
            for movie_item, library in zip(movie_items, libraries):
                artwork["library"] = library
                artwork["media_type"] = MediaType.MOVIE.value
                if movie_item.title != artwork["title"]:
                    artwork["alt_title"] = movie_item.title
                if hasattr(movie_item, "ratingKey"):
                    artwork["ratingKey"] = movie_item.ratingKey
                if hasattr(movie_item, "labels"):
                    item_labels = [str(label) for label in movie_item.labels]
                    artwork["overlay"] = KOMETA_OVERLAY_LABEL in item_labels

                # Use the actual movie title from Plex in case it differs from the artwork title (if it's a foreign title, etc.)
                alt_title = artwork.get("alt_title", None)
                desc = description.replace(artwork["title"], alt_title) if alt_title else description
                item_path = normalize_path(movie_item.media[0].parts[0].file)
                path_parts = []
                path_parts = get_path_parts(item_path)

                if self.local_assets or self.kometa:

                    saver = KometaSaver(artwork_type, library)
                    saver.download_timeout = self.config.kometa_download_timeout
                    saver.retry_attempts = self.config.upload_retry_attempts
                    saver.retry_backoff = self.config.upload_retry_backoff_seconds
                    saver.set_artwork(artwork)

                    if self.local_assets:
                        movie_path = os.path.dirname(item_path)

                        normalized_mappings = [{
                            "plex_path": normalize_path(mapping.get("plex_path", "")),
                            "app_path": normalize_path(mapping.get("app_path", ""))
                        } for mapping in globals.config.path_mappings]
                        
                        remapped = False
                        for mapping in normalized_mappings:
                            if mapping["plex_path"] in movie_path:
                                self.callbacks.debug(f"Replacing {mapping["plex_path"]} for {mapping["app_path"]}")
                                movie_path = movie_path.replace(mapping["plex_path"], mapping["app_path"])
                                remapped = True

                        if not os.path.exists(movie_path):
                            self.callbacks.debug(f"ERROR: Path '{movie_path}' does not exist")
                            result = f"❌ {desc} | Error saving asset: {movie_path} {f'({os.path.dirname(item_path)}) ' if remapped else ''}does not exist"
                            self.callbacks.log(message=result)
                            self.callbacks.record_result(result=result)
                            continue

                        saver.dest_dir = movie_path
                    
                    elif self.kometa:
                        asset_folder = path_parts[-2]
                        base_dir = (DOCKER_KOMETA_TEMP_PATH if self.options.temp else DOCKER_KOMETA_ASSETS_PATH) if globals.docker else getattr(globals.config, "temp_dir" if self.options.temp else "kometa_base", None)
                        saver.dest_dir = os.path.join(base_dir, library, asset_folder)

                    self.callbacks.debug(f"Destination directory is {saver.dest_dir}")
                    saver.dest_file_name = ARTWORK_FILENAME_MAP.get(artwork.get('file_type'), 'poster')
                    saver.dest_file_ext = ".jpg"
                    saver.set_description(desc)
                    saver.set_options(self.options)
                    if locally_matched:
                        saver.confirm_match = lambda a=artwork, item=movie_item: self._artwork_matches_item(a, item, "movie")
                    result = saver.save_to_kometa()
                    if result.startswith("✅"):
                        artwork["status"] = "new"
                    elif result.startswith("♻️"):
                        artwork["status"] = "updated"                    
                    if self.local_assets and (result.startswith("✅") or result.startswith("♻️")):
                        movie_item.refresh()
                    self.callbacks.log(message=result)
                    self.callbacks.record_result(result=result, artwork=artwork if self.kometa_auto_run else None)
                else:
                    uploader = PlexUploader(movie_item, artwork_type, artwork_id)
                    uploader.set_artwork(artwork)
                    uploader.track_artwork_ids = self.config.track_artwork_ids
                    uploader.reset_overlay = self.config.reset_overlay
                    uploader.skip_locked = self.skip_locked
                    uploader.allow_artist_updates = self.allow_artist_updates
                    uploader.artist_assets = self.artist_assets
                    uploader.retry_attempts = self.config.upload_retry_attempts
                    uploader.retry_backoff = self.config.upload_retry_backoff_seconds
                    if locally_matched:
                        uploader.confirm_match = lambda a=artwork, item=movie_item: self._artwork_matches_item(a, item, "movie")
                    uploader.set_description(desc)
                    uploader.set_options(self.options)
                    result = uploader.upload_to_plex()
                    self.callbacks.log(message=result)
                    self.callbacks.record_result(result=result)
        else:
            raise MovieNotFound(f'{description} | {artwork_type} not processed (Movie not available on Plex)')


    def process_tv_artwork(self, artwork: TVArtwork) -> Optional[str]:

        description = "Target media"
        upload_target = None
        artwork_type = None
        artwork_id = None
        result = None
        self.staging: bool = self.kometa and (globals.config.stage_assets or self.options.stage)

        season = artwork.get('season')
        if is_numeric(season) and season == 0:
            season = "Specials"
        elif season:
            season = f"Season {artwork['season']:02}"
#
        if artwork['season'] is None and artwork['episode'] is None:
            raise ShowNotFound(f"{artwork['title']} ({artwork['year']}) • {artwork['author']} | Not available on Plex")
        elif is_numeric(artwork['season']) and is_numeric(artwork['episode']):
            description = f"{artwork['title']} ({artwork['year']}) • {artwork['author']} • {season} • Episode {artwork['episode']:02}"
        elif (artwork['episode'] is None or artwork['episode'] == "Cover") and is_numeric(artwork['season']):
            description = f"{artwork['title']} ({artwork['year']}) • {artwork['author']} • {season}"
        elif artwork['season'] is None or artwork['season'] == "Cover" or artwork['season'] == "Backdrop" or artwork['season'].startswith("SquareArt"):
            description = f"{artwork['title']} ({artwork['year']}) • {artwork['author']}"

        artwork['year'] = self.options.year if self.options.year else artwork['year']
        artwork_type = ARTWORK_TYPE_MAP.get(artwork.get('file_type'))
        
        # Since the TPDb scraper doesn't fetch the TMDb ID up front for each poster, we resolve it here
        locally_matched = self._resolve_tmdb_id(artwork, description, MediaType.TV_SHOW)

        try:
            tv_show_items, libraries = self.plex.find_in_library(MediaType.TV_SHOW, artwork)
        except PlexConnectorException as e:
            raise PlexConnectorException(str(e))
        except Exception as e:
            raise Exception from e

        if tv_show_items:
            self.callbacks.debug(f"Found TMDb ID '{artwork.get('tmdb_id')}' in {len(libraries)} libraries.")
            for tv_show, library in zip(tv_show_items, libraries):
                artwork["library"] = library
                artwork["media_type"] = MediaType.TV_SHOW.value
                if title_cleaner(tv_show.title) != artwork["title"]:
                    artwork["alt_title"] = title_cleaner(tv_show.title)
                if hasattr(tv_show, "ratingKey"):
                    artwork["ratingKey"] = tv_show.ratingKey
                item_labels = [str(label) for label in tv_show.labels] if hasattr(tv_show, "labels") else []
                artwork["overlay"] = KOMETA_OVERLAY_LABEL in item_labels
                # Use the actual TV show title from Plex in case it differs from the artwork title (if it's a foreign title, etc.)
                alt_title = artwork.get("alt_title", None)
                desc = description.replace(artwork['title'], alt_title) if alt_title else description
                # Use the year from Plex if it differs
                plex_year = getattr(tv_show, "year", None)
                desc = desc.replace(f"({artwork['year']})", f'({plex_year})') if plex_year else desc
                item_path = normalize_path(tv_show.seasons()[0].episodes()[0].media[0].parts[0].file)
                path_parts = []
                path_parts = get_path_parts(item_path)
                has_season_folders = path_parts[-2].lower().startswith("season") or path_parts[-2].lower().startswith("specials")
                asset_folder = path_parts[-3] if has_season_folders else path_parts[-2]
                show_path = os.path.dirname(os.path.dirname(item_path)) if has_season_folders else os.path.dirname(item_path)

                try:
                    if isinstance(artwork['season'], str):
                        # This is a show-level asset, it could be a show cover, background or square art
                        final_path = show_path
                        if artwork['season'] == "Cover":
                            upload_target = tv_show
                            file_name = "poster"
                        elif artwork['season'] == "Backdrop":
                            upload_target = tv_show
                            file_name = "background"
                        elif "SquareArt" in artwork['season']:
                            sq = artwork['season'].split("_")[-1]
                            upload_target = tv_show
                            if sq == "0":
                                # For the first square art asset processed, we set the upload target (for Plex uploads)
                                # and the file_name to 'square.ext' for Kometa asset directory
                                file_name = "square"
                            elif self.kometa:
                                # If there's more than one square art asset in the set and we're saving to Kometa asset directory,
                                # we save the additional assets as 'square_alt_#.ext' so the user can rename the one they want to use
                                file_name = f"square_alt_{sq}"
                            else:
                                # If we're applying directly to a Plex server, only process the first one and ignore the rest
                                result = f"⚠️ {desc} | Ignoring additional square art asset"
                                self.callbacks.log(message=result)
                                self.callbacks.record_result(result=result)
                                continue

                    elif is_numeric(artwork['season']):
                        # This is either a season asset (season cover) or an episode asset (title card)
                        if artwork['season'] >= 0:
                            is_season_available = artwork['season'] in [S.index for S in tv_show.seasons()]
                            if is_season_available:
                                _season = tv_show.season(artwork['season'])
                                artwork["parent_key"] = getattr(tv_show, "ratingKey", None)
                                artwork["ratingKey"] = getattr(_season, "ratingKey", artwork["parent_key"])
                                _s_labels = [str(label) for label in _season.labels] if hasattr(_season, "labels") else []
                                artwork["overlay"] = KOMETA_OVERLAY_LABEL in _s_labels
                            else:
                                artwork.pop("ratingKey", None)

                            if self.local_assets and is_season_available:
                                item_path = normalize_path(tv_show.season(artwork['season']).episodes()[0].media[0].parts[0].file)
                                season_folder = os.path.basename(os.path.dirname(item_path)) if has_season_folders else ""
                                final_path = os.path.join(show_path, season_folder) if has_season_folders else show_path

                            if artwork['episode'] == "Cover" or artwork['episode'] is None:
                                # This is a season cover
                                if is_season_available or (self.staging and season != "Specials"):
                                    self.callbacks.debug(f"Staging is {'enabled' if self.staging else 'disabled'}")
                                    file_name = f"Season{artwork['season']:02}"

                                    if artwork['season'] == 0 and self.local_assets:
                                        file_name = "season-specials-poster"

                                    if not self.kometa:
                                        upload_target = _season
                                else:
                                    result = f"⚠️ {desc} | {season} not available in {library}"
                                    self.callbacks.log(message=result)
                                    self.callbacks.record_result(result=result)
                                    continue

                            elif is_numeric(artwork['episode']) and artwork['episode'] >= 0:
                                # This is a title card
                                if is_season_available or (self.staging and season != "Specials"):
                                    is_episode_available = artwork['episode'] in [E.index for E in tv_show.season(artwork['season']).episodes()] if is_season_available else False
                                    if is_episode_available:
                                        _episode = tv_show.season(artwork['season']).episode(artwork['episode'])
                                        artwork["parent_key"] = getattr(tv_show, "ratingKey", None)
                                        artwork["ratingKey"] = getattr(_episode, "ratingKey", artwork["parent_key"])
                                        _e_labels = [str(label) for label in _episode.labels] if hasattr(_episode, "labels") else []
                                        artwork["overlay"] = KOMETA_OVERLAY_LABEL in _e_labels
                                    else:
                                        artwork.pop("ratingKey", None)

                                    if (is_season_available and is_episode_available) or self.staging:
                                        file_name = f"S{artwork['season']:02}E{artwork['episode']:02}"
                                        if self.local_assets and is_episode_available:
                                            # To save as local asset the filename has to match the episode filename
                                            ep_path = tv_show.season(artwork['season']).episode(artwork['episode']).media[0].parts[0].file
                                            file_name = os.path.splitext(get_path_parts(ep_path)[-1])[0]
                                        if not self.kometa:
                                            upload_target = _episode
                                    else:
                                        result = f"⚠️ {desc} | {season}, Episode {artwork['episode']:02} not available in {library}"
                                        self.callbacks.log(message=result)
                                        self.callbacks.record_result(result=result)
                                        continue
                                else:
                                    result = f"⚠️ {desc} | {season} not available in {library}"
                                    self.callbacks.log(message=result)
                                    self.callbacks.record_result(result=result)
                                    continue

                except (AttributeError, KeyError, NotFound) as e:
                    raise ShowNotFound(f"{desc} | Not available on Plex in {library}: {e}") from e
                    
                try:
                    if self.local_assets or self.kometa:
                        saver = KometaSaver(artwork_type, library)
                        saver.download_timeout = self.config.kometa_download_timeout
                        saver.retry_attempts = self.config.upload_retry_attempts
                        saver.retry_backoff = self.config.upload_retry_backoff_seconds
                        saver.set_artwork(artwork)

                        if self.local_assets and upload_target:
                            normalized_mappings = [{
                                "plex_path": normalize_path(mapping.get("plex_path", "")),
                                "app_path": normalize_path(mapping.get("app_path", ""))
                            } for mapping in globals.config.path_mappings]

                            remapped = False
                            for mapping in normalized_mappings:
                                if mapping["plex_path"] in final_path:
                                    self.callbacks.debug(f"Replacing {mapping["plex_path"]} for {mapping["app_path"]}")
                                    final_path = final_path.replace(mapping["plex_path"], mapping["app_path"])
                                    remapped = True

                            if not os.path.exists(final_path):
                                self.callbacks.debug(f"ERROR: Path '{final_path}' does not exist")
                                result = f"❌ {desc} | Error saving asset: {final_path} {f'({os.path.dirname(item_path)}) ' if remapped else ''}does not exist"
                                self.callbacks.log(message=result)
                                self.callbacks.record_result(result=result)
                                continue

                            saver.dest_dir = final_path

                        elif self.kometa:
                            base_dir = (DOCKER_KOMETA_TEMP_PATH if self.options.temp else DOCKER_KOMETA_ASSETS_PATH) if globals.docker else getattr(globals.config, 'temp_dir' if self.options.temp else 'kometa_base', None)
                            saver.dest_dir = os.path.join(base_dir, library, asset_folder)

                        self.callbacks.debug(f"Destination directory is {saver.dest_dir}")
                        saver.dest_file_name = file_name
                        saver.dest_file_ext = ".jpg"
                        saver.set_description(desc)
                        saver.set_options(self.options)

                        if locally_matched:
                            saver.confirm_match = lambda a=artwork, item=tv_show: self._artwork_matches_item(a, item, "tv")
                        
                        result = saver.save_to_kometa()
                        if result.startswith("✅"):
                            artwork["status"] = "new"
                        elif result.startswith("♻️"):
                            artwork["status"] = "updated"                                             

                        if self.local_assets and upload_target and (result.startswith("✅") or result.startswith("♻️")):
                            upload_target.refresh()

                        self.callbacks.log(message=result)
                        self.callbacks.record_result(result=result, artwork=artwork if self.kometa_auto_run else None)

                    elif upload_target:
                        artwork_id = ARTWORK_ID_MAP.get(artwork.get('file_type'))
                        uploader = PlexUploader(upload_target, artwork_type, artwork_id)
                        uploader.set_artwork(artwork)
                        uploader.track_artwork_ids = self.config.track_artwork_ids
                        uploader.reset_overlay = self.config.reset_overlay
                        uploader.skip_locked = self.skip_locked
                        uploader.allow_artist_updates = self.allow_artist_updates
                        uploader.artist_assets = self.artist_assets
                        uploader.retry_attempts = self.config.upload_retry_attempts
                        uploader.retry_backoff = self.config.upload_retry_backoff_seconds
                        if locally_matched:
                            uploader.confirm_match = lambda a=artwork, item=tv_show: self._artwork_matches_item(a, item, "tv")
                        uploader.set_description(desc)
                        uploader.set_options(self.options)
                        result = uploader.upload_to_plex()
                        self.callbacks.log(message=result)
                        self.callbacks.record_result(result=result)
                except Exception:
                    raise
        else:
            raise ShowNotFound(f"{description} | {artwork_type} not processed (Show not available on Plex)")

