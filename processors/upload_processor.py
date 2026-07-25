from typing import Optional

from core.config import Config
from core.exceptions import CollectionNotFound, MovieNotFound, ShowNotFound, PlexConnectorException
from core.enums import ScraperSource
from core.exceptions import ScraperException
from core.constants import ARTWORK_ID_MAP, ARTWORK_TYPE_MAP, ARTWORK_FILENAME_MAP
from models.options import Options
from plex.plex_connector import PlexConnector
from plex.plex_uploader import PlexUploader
from plex.library_index import PlexLibraryIndex
from plexapi.exceptions import NotFound
from kometa.kometa_saver import KometaSaver
from utils import soup_utils
from utils.utils import is_numeric, get_path_parts
from models.artwork_types import MovieArtwork, TVArtwork, CollectionArtwork
import os
from core import globals
from utils.notifications import debug_me

class UploadProcessor:

    def __init__(self, plex: PlexConnector) -> None:
        self.plex: PlexConnector = plex
        self.options: Options = Options()
        self.config: Config = Config()
        self.config.load()
        self._media_index: Optional[PlexLibraryIndex] = None
        self._match_confirm_cache: dict = {}


    def set_options(self, options: Options) -> None:
        self.options = options
        self.kometa: bool = self.options.kometa or globals.config.save_to_kometa
        self.skip_locked: bool = self.options.skip_locked or globals.config.skip_locked_artwork

    def _resolve_tmdb_id(self, artwork, description: str, kind: str) -> bool:
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
            if self._media_index is None:
                self._media_index = PlexLibraryIndex(self.plex.movie_libraries, self.plex.tv_libraries)
            status, tmdb_id = self._media_index.lookup(kind, artwork.get("title"), artwork.get("year"))
            if status == "not_found":
                if kind == "movie":
                    raise MovieNotFound(f'{description} | Movie not available on Plex')
                raise ShowNotFound(f'{description} | Show not available on Plex')
            if status == "matched":
                debug_me(f"Matched '{artwork.get('title')} ({artwork.get('year')})' locally as TMDb ID '{tmdb_id}'", "UploadProcessor/_resolve_tmdb_id")
                artwork["tmdb_id"] = tmdb_id
                return True
            debug_me(f"'{artwork.get('title')} ({artwork.get('year')})' is ambiguous locally, fetching the poster page", "UploadProcessor/_resolve_tmdb_id")

        self._fetch_tmdb_id_from_tpdb(artwork, description)
        return False

    def _fetch_tmdb_id_from_tpdb(self, artwork, description: str) -> None:
        """Fetch the poster page from ThePosterDB to read its TMDb ID (data-media-id), falling back
           to a local Plex title/year search if the page doesn't expose one."""
        poster_id = artwork.get("id", None)
        poster_page_url = f"https://theposterdb.com/poster/{poster_id}"
        debug_me(f"Fetching TMDb ID from '{poster_page_url}'", "UploadProcessor/_fetch_tmdb_id_from_tpdb")
        try:
            poster_page_soup = soup_utils.cook_soup(poster_page_url)
        except ScraperException as e:
            debug_me(f"Unable to fetch TMDb ID due to error: {str(e)}", "UploadProcessor/_fetch_tmdb_id_from_tpdb")
            raise ScraperException(f"{description} | {str(e)}") from None
        try:
            artwork["tmdb_id"] = int(poster_page_soup.find('div', {"data-media-id": True})['data-media-id'])
        except (KeyError, TypeError, ValueError) as e:
            debug_me(f"Failed to extract TMDb ID from poster page, trying another way. Error was: {e}", "UploadProcessor/_fetch_tmdb_id_from_tpdb")
            _, artwork["tmdb_id"], _, _ = self.plex.movie_or_show(artwork.get("title"), artwork.get("year"))
            debug_me(f"Found TMDb ID '{artwork['tmdb_id']}' for '{artwork.get('title')}' using Plex search.", "UploadProcessor/_fetch_tmdb_id_from_tpdb")

    def _artwork_matches_item(self, artwork, plex_item, kind: str) -> bool:
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
        debug_me(f"Confirming local match for '{artwork.get('title')}' from '{poster_page_url}'", "UploadProcessor/_artwork_matches_item")
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

        try:
            collection_items, libraries = self.plex.find_collection(artwork['title'])
            if not collection_items:
                collection_items, libraries = self.plex.find_collection(artwork['title'].replace(" Collection",""))
        except PlexConnectorException as e:
            raise PlexConnectorException(f"Error searching Plex for {artwork['title']}")
        except Exception as e:
            raise Exception from e

        result = None
        results = []
        description = f"{artwork['title']} • {artwork['author']}"
        artwork_type = ARTWORK_TYPE_MAP.get(artwork.get('file_type'))
        artwork_id = ARTWORK_ID_MAP.get(artwork.get('file_type'))

        if collection_items:
            debug_me(f"Found collection '{artwork['title']}' in {len(libraries)} libraries.")
            for collection_item, library in zip(collection_items, libraries):
                if self.kometa:
                    asset_folder = collection_item.title.replace("/", "").replace(":", "")
                    saver = KometaSaver(artwork_type, library)
                    saver.set_artwork(artwork)
                    base_dir = ("/temp" if self.options.temp else "/assets") if globals.docker else getattr(globals.config, "temp_dir" if self.options.temp else "kometa_base", None)
                    saver.dest_dir = os.path.join(base_dir, library, asset_folder)
                    debug_me(f"Destination directory is {saver.dest_dir}")
                    saver.dest_file_name = ARTWORK_FILENAME_MAP.get(artwork.get('file_type'), 'poster')
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
                    uploader.skip_locked = self.skip_locked
                    uploader.set_description(description)
                    uploader.set_options(self.options)
                    result = uploader.upload_to_plex()
                    results.append(result)
        else:
            raise CollectionNotFound(f'{description} | {artwork_type} not processed (Collection not available on Plex)')
        return results

    def process_movie_artwork(self, artwork: MovieArtwork) -> Optional[str]:

        artwork['year'] = self.options.year if self.options.year else artwork['year']
        
        result = None
        results = []
        description = f"{artwork['title']} ({artwork['year']}) • {artwork['author']}"
        artwork_type = ARTWORK_TYPE_MAP.get(artwork.get('file_type'))
        artwork_id = ARTWORK_ID_MAP.get(artwork.get('file_type'))

        # Since the TPDb scraper doesn't fetch the TMDb ID up front for each poster, we resolve it here
        locally_matched = self._resolve_tmdb_id(artwork, description, "movie")

        try:
            movie_items, libraries = self.plex.find_in_library("movie", artwork)
        except PlexConnectorException as e:
            raise PlexConnectorException(str(e))
        except Exception as e:
            raise Exception from e

        if movie_items:
            debug_me(f"Found TMDb ID '{artwork.get('tmdb_id')}' in {len(libraries)} libraries.")
            for movie_item, library in zip(movie_items, libraries):
                # Use the actual movie title from Plex in case it differs from the artwork title (if it's a foreign title, etc.)
                desc = description.replace(artwork["title"], movie_item.title) if movie_item.title != artwork["title"] else description
                if self.kometa:
                    item_path = movie_item.media[0].parts[0].file
                    path_parts = []
                    path_parts = get_path_parts(item_path)
                    asset_folder = path_parts[-2]
                    saver = KometaSaver(artwork_type, library)
                    saver.set_artwork(artwork)
                    base_dir = ("/temp" if self.options.temp else "/assets") if globals.docker else getattr(globals.config, "temp_dir" if self.options.temp else "kometa_base", None)
                    saver.dest_dir = os.path.join(base_dir, library, asset_folder)
                    debug_me(f"Destination directory is {saver.dest_dir}")
                    saver.dest_file_name = ARTWORK_FILENAME_MAP.get(artwork.get('file_type'), 'poster')
                    saver.dest_file_ext = ".jpg"
                    saver.set_description(desc)
                    saver.set_options(self.options)
                    if locally_matched:
                        saver.confirm_match = lambda a=artwork, item=movie_item: self._artwork_matches_item(a, item, "movie")
                    result = saver.save_to_kometa()
                    results.append(result)
                else:
                    uploader = PlexUploader(movie_item, artwork_type, artwork_id)
                    uploader.set_artwork(artwork)
                    uploader.track_artwork_ids = self.config.track_artwork_ids
                    uploader.reset_overlay = self.config.reset_overlay
                    uploader.skip_locked = self.skip_locked
                    if locally_matched:
                        uploader.confirm_match = lambda a=artwork, item=movie_item: self._artwork_matches_item(a, item, "movie")
                    uploader.set_description(desc)
                    uploader.set_options(self.options)
                    result = uploader.upload_to_plex()
                    results.append(result)
        else:
            raise MovieNotFound(f'{description} | {artwork_type} not processed (Movie not available on Plex)')
        return results


    def process_tv_artwork(self, artwork: TVArtwork) -> Optional[str]:

        description = "Target media"
        upload_target = None
        artwork_type = None
        artwork_id = None
        result = None
        results = []
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
        locally_matched = self._resolve_tmdb_id(artwork, description, "tv")

        try:
            tv_show_items, libraries = self.plex.find_in_library("tv", artwork)
        except PlexConnectorException as e:
            raise PlexConnectorException(str(e))
        except Exception as e:
            raise Exception from e

        if tv_show_items:
            debug_me(f"Found TMDb ID '{artwork.get('tmdb_id')}' in {len(libraries)} libraries.")
            for tv_show, library in zip(tv_show_items, libraries):
                # Use the actual TV show title from Plex in case it differs from the artwork title (if it's a foreign title, etc.)
                desc = description.replace(artwork['title'], tv_show.title.split(' (')[0]) if tv_show.title.split(' (')[0] != artwork['title'] else description
                # Use the year from Plex if it differs
                desc = desc.replace(f"({artwork['year']})", f"({tv_show.year})") if tv_show.year and artwork['year'] != tv_show.year else desc
                item_path = tv_show.seasons()[0].episodes()[0].media[0].parts[0].file
                path_parts = []
                path_parts = get_path_parts(item_path)
                asset_folder = path_parts[-3] if path_parts[-2].lower().startswith("season") or path_parts[-2].lower().startswith("specials") else path_parts[-2]
                try:
                    if isinstance(artwork['season'], str):
                        if artwork['season'] == "Cover":
                            upload_target = tv_show
                            file_name = "poster"
                        elif artwork['season'] == "Backdrop":
                            upload_target = tv_show
                            file_name = "background"
                        elif "SquareArt" in artwork['season']:
                            sq = artwork['season'].split("_")[-1]
                            if sq == "0":
                                # For the first square art asset processed, we set the upload target (for Plex uploads)
                                # and the file_name to 'square.ext' for Kometa asset directory
                                upload_target = tv_show
                                file_name = "square"
                            elif self.kometa:
                                # If there's more than one square art asset in the set and we're saving to Kometa asset directory,
                                # we save the additional assets as 'square_alt_#.ext' so the user can rename the one they want to use
                                file_name = f"square_alt_{sq}"
                            else:
                                # If we're applying directly to a Plex server, only process the first one and ignore the rest
                                result = f"⚠️ {desc} | Ignoring additional square art asset"
                                results.append(result)
                                continue
                    elif is_numeric(artwork['season']):
                        if artwork['season'] >= 0:
                            if artwork['episode'] == "Cover" or artwork['episode'] is None:
                                if artwork['season'] in [S.index for S in tv_show.seasons()] or (self.staging and season != "Specials"):
                                    debug_me(f"Staging is {'enabled' if self.staging else 'disabled'}.")
                                    file_name = f"Season{artwork['season']:02}"
                                    if not self.kometa:
                                        upload_target = tv_show.season(artwork['season'])
                                else:
                                    result = f"⚠️ {desc} | {season} not available in {library}"
                                    results.append(result)
                                    continue
                            elif is_numeric(artwork['episode']) and artwork['episode'] >= 0:
                                if (artwork['season'] in [S.index for S in tv_show.seasons()]) or (self.staging and season != "Specials"):
                                    if ((artwork['season'] in [S.index for S in tv_show.seasons()]) and (artwork['episode'] in [E.index for E in tv_show.season(artwork['season']).episodes()])) or self.staging:
                                        file_name = f"S{artwork['season']:02}E{artwork['episode']:02}"
                                        if not self.kometa:
                                            upload_target = tv_show.season(artwork['season']).episode(artwork['episode'])
                                    else:
                                        result = f"⚠️ {desc} | {season}, Episode {artwork['episode']:02} not available in {library}"
                                        results.append(result)
                                        continue
                                else:
                                    result = f"⚠️ {desc} | {season} not available in {library}"
                                    results.append(result)
                                    continue

                except (AttributeError, KeyError, NotFound) as e:
                    raise ShowNotFound(f"{desc} | Not available on Plex in {library}: {e}") from e
                    
                try:
                    if self.kometa:
                        saver = KometaSaver(artwork_type, library)
                        saver.set_artwork(artwork)
                        base_dir = ("/temp" if self.options.temp else "/assets") if globals.docker else getattr(globals.config, 'temp_dir' if self.options.temp else 'kometa_base', None)
                        saver.dest_dir = os.path.join(base_dir, library, asset_folder)
                        debug_me(f"Destination directory is {saver.dest_dir}")
                        saver.dest_file_name = file_name
                        saver.dest_file_ext = ".jpg"
                        saver.set_description(desc)
                        saver.set_options(self.options)
                        if locally_matched:
                            saver.confirm_match = lambda a=artwork, item=tv_show: self._artwork_matches_item(a, item, "tv")
                        result = saver.save_to_kometa()
                        results.append(result)
                    elif upload_target:
                        artwork_id = ARTWORK_ID_MAP.get(artwork.get('file_type'))
                        uploader = PlexUploader(upload_target, artwork_type, artwork_id)
                        uploader.set_artwork(artwork)
                        uploader.track_artwork_ids = self.config.track_artwork_ids
                        uploader.reset_overlay = self.config.reset_overlay
                        uploader.skip_locked = self.skip_locked
                        if locally_matched:
                            uploader.confirm_match = lambda a=artwork, item=tv_show: self._artwork_matches_item(a, item, "tv")
                        uploader.set_description(desc)
                        uploader.set_options(self.options)
                        result = uploader.upload_to_plex()
                        results.append(result)
                except Exception:
                    raise
        else:
            raise ShowNotFound(f"{description} | {artwork_type} not processed (Show not available on Plex)")

        return results

