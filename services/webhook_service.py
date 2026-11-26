"""
In-tool Sonarr/Radarr import webhook.

On a Radarr/Sonarr "Download" (import) event, look the imported title up in the persistent
asset index and apply the cached poster through the normal upload path, retrying for a few
minutes while Plex finishes scanning the new file. Everything downstream of the dispatch (the
authoritative TMDb resolution, artwork-ID skips, locked-artwork skips, Kometa mode) is the same
code a normal scrape uses, so the webhook inherits all of it without re-implementing any of it.
"""

import threading, time, re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import FrozenSet, List, Optional, Tuple, Union

from core import globals
from core.constants import WEBHOOK_RETRY_DELAYS, IMAGE_EXTENSIONS, KOMETA_OVERLAY_LABEL
from core.enums import ScraperSource, RunType, RunTrigger, RunOutcome, WebhookSource, FileType, MediaType
from core.exceptions import MovieNotFound, ShowNotFound
from models.callbacks import ProcessingCallbacks
from models.instance import Instance
from models.options import Options
from services.asset_index import AssetIndex, normalize_title
from services.run_history import RunHistory

# The *arr app that sent the event, as the history records it
_TRIGGER_BY_SOURCE = {WebhookSource.RADARR.value: RunTrigger.RADARR.value, WebhookSource.SONARR.value: RunTrigger.SONARR.value}


def _log(text: str) -> None:
    # utils.notifications imports the services package, so import it lazily to avoid an import
    # cycle when the services package pulls this module in at start-up.
    from utils.notifications import update_log
    update_log(Instance(broadcast=True), text)


def _debug(message: str, context: Optional[str] = None) -> None:
    from utils.notifications import debug_me
    debug_me(message, context)

def _clean_title(title: str) -> str:
    """Removes year in parenthesis from title"""
    return re.sub(r'\s*\(\d{4}\)$', '', title.strip())


@dataclass(frozen=True)
class WebhookEvent:
    """A parsed Sonarr/Radarr import event."""
    kind: str                      # "movie" or "tv"
    title: str
    year: Optional[int]
    tmdb_id: Optional[int]
    tvdb_id: Optional[int]
    seasons: FrozenSet[int]
    episodes: FrozenSet[Tuple[int, int]]
    source: str                    # "radarr" or "sonarr"
    is_upgrade: bool = False
    media_folder: Optional[str] = None     # name of the movie's folder, when Radarr says
    media_file: Tuple[str, ...] = ()       # the imported file's path inside that folder

    @property
    def label(self) -> str:
        # Remove the year from the title if the title contains it to avoid duplicating it
        clean_title = _clean_title(self.title)
        return f"{clean_title} ({self.year})" if self.year else self.title # Keeps the year in the title if the year is not present in the event


def _int_or_none(value) -> Optional[int]:
    """Map absent numeric fields to None. Radarr/Sonarr serialise absent ints and years as 0
       (C# defaults), so 0 is treated as absent. NOT used for season numbers, where 0 (Specials)
       is a real value."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number or None


def _imported_media_path(payload: dict, movie: dict) -> Tuple[Optional[str], Tuple[str, ...]]:
    """Where a Radarr import landed: the name of the movie's folder, and the file's path inside
       it. Radarr sends movie.folderPath, and movieFile.path, which is folderPath joined with
       movieFile.relativePath. Only the part from the movie's folder down is kept, because Radarr
       and Plex usually mount the library under different roots. The folder is None when the
       event names no path, and the file is empty when it names only the folder."""
    # utils.utils imports utils.notifications, which imports the services package (see _log).
    from utils.utils import get_path_parts

    def parts_of(value) -> Tuple[str, ...]:
        return tuple(get_path_parts(value.strip())) if isinstance(value, str) and value.strip() else ()

    movie_file = payload.get("movieFile") if isinstance(payload.get("movieFile"), dict) else {}
    folder_path = parts_of(movie.get("folderPath"))
    file_path = parts_of(movie_file.get("path"))
    relative = parts_of(movie_file.get("relativePath"))
    if file_path and not relative:
        relative = file_path[-1:]

    if len(folder_path) > 1:
        folder = folder_path[-1]
    elif len(file_path) > len(relative) + 1:
        folder = file_path[-len(relative) - 1]
    else:
        return None, ()
    return folder, relative


def parse_event(payload: dict) -> Union[WebhookEvent, str, None]:
    """Parse a Radarr/Sonarr webhook payload.

       Returns a WebhookEvent for an import ("Download") event, the string "test" for the
       connection Test button, or None for any other event type or malformed payload. Never
       raises, so an unexpected payload is acknowledged and ignored rather than erroring."""
    _debug(f"Parsing webhook event with payload:")
    _debug(payload)

    if not isinstance(payload, dict):
        return None
    event_type = payload.get("eventType")
    if event_type == "Test":
        return "test"
    if event_type != "Download":
        return None
    movie = payload.get("movie")
    if isinstance(movie, dict) and movie.get("title"):
        media_folder, media_file = _imported_media_path(payload, movie)
        return WebhookEvent(
            kind="movie",
            title=movie["title"],
            year=_int_or_none(movie.get("year")),
            tmdb_id=_int_or_none(movie.get("tmdbId")),
            tvdb_id=None,
            seasons=frozenset(),
            episodes=frozenset(),
            source=WebhookSource.RADARR.value,
            media_folder=media_folder,
            media_file=media_file
        )
    series = payload.get("series")
    if isinstance(series, dict) and series.get("title"):
        _episodes = payload.get("episodes") or []
        episodes = frozenset(
            (episode["seasonNumber"], episode["episodeNumber"])
            for episode in _episodes
            if isinstance(episode, dict)
            and isinstance(episode.get("seasonNumber"), int)
            and isinstance(episode.get("episodeNumber"), int)
        )
        seasons = frozenset(
            season for season, _ in episodes
        )
        return WebhookEvent(
            kind="tv",
            title=series["title"],
            year=_int_or_none(series.get("year")),
            tmdb_id=_int_or_none(series.get("tmdbId")),
            tvdb_id=_int_or_none(series.get("tvdbId")),
            seasons=seasons,
            episodes=episodes,
            is_upgrade=bool(payload.get("isUpgrade", False)),
            source=WebhookSource.SONARR.value
        )
    return None


class WebhookService:
    """Applies cached artwork for imported titles off the request thread, with a retry ladder
       for the window where an item has been imported but Plex has not scanned it in yet."""

    def __init__(self) -> None:
        self._inflight: set = set()
        self._lock = threading.Lock()

    def enqueue(self, event: WebhookEvent) -> None:
        """Queue an import event for application. Returns immediately; work happens on a thread."""
        key = self._dedupe_key(event)
        with self._lock:
            if key in self._inflight:
                _debug(f"Import for {event.label} is already pending, ignoring the duplicate")
                return
            self._inflight.add(key)
        # One history record covers the whole event, retries included, so the run starts
        # counting from the moment it was accepted and the tally survives every attempt.
        started_at = datetime.now(timezone.utc).isoformat()
        tally = ProcessingCallbacks(
            on_log_update=_log,
            on_debug=_debug
        )
        # Wait a configurable delay before the first attempt: the *arr apps fire the webhook the
        # moment they import a file, usually before Plex has scanned it in, so give Plex a head
        # start. If it is still not ready by then, the retry ladder takes over.
        delay = max(0, globals.config.webhook_apply_delay or 0)
        timer = threading.Timer(delay, self._attempt, args=(event, key, started_at, tally))
        timer.daemon = True
        timer.start()

    @staticmethod
    def _dedupe_key(event: WebhookEvent):
        # An edition in its own folder shares the plain release's TMDb ID, so the folder keeps
        # an import of each apart.
        identity = event.tmdb_id or event.tvdb_id or normalize_title(event.title)
        return (event.kind, identity, event.seasons, event.episodes, event.media_folder)

    def _release(self, key) -> None:
        with self._lock:
            self._inflight.discard(key)

    def _attempt(self, event: WebhookEvent, key, started_at: str, tally: ProcessingCallbacks,
                 attempt: int = 0, artwork: Optional[List[dict]] = None,
                 log_file: Optional[str] = None) -> None:
        _debug(f"Processing webhook event with key {key}, attempt #{attempt+1}")
        # UploadProcessor pulls in the processors -> plex chain; import it here so the services
        # package does not drag that in at start-up (mirrors the app's own lazy-import pattern).
        from processors.upload_processor import UploadProcessor
        outcome = RunOutcome.FAILED.value
        try:
            # Kometa staged asset pipeline
            if artwork is None and globals.config.save_to_kometa and globals.config.kometa_auto_run and event.kind == "tv":
                globals.plex.connect()
                # Check if there are staged Kometa assets to apply
                asset_map, not_ready = self._resolve_staged_artwork(event)
                if not asset_map and not_ready:
                    if attempt < len(WEBHOOK_RETRY_DELAYS):
                        delay = WEBHOOK_RETRY_DELAYS[attempt]
                        _debug(f"{event.label} not in Plex yet, retrying in {delay}s")
                        timer = threading.Timer(
                            delay, self._attempt, args=(event, key, started_at, tally, attempt + 1, None, None)
                        )
                        timer.daemon = True
                        timer.start()
                        return
                    _log(f"⚠️ Webhook • {event.label} | Imported episodes or seasons have not appeared in Plex, unable check for staged assets")
                    self._release(key)
                    return

                if asset_map:
                    _log(f"📥 Webhook • {event.label} | {event.source.title()} import: queueing for Kometa updates")
                    self._release(key)
                    globals.kometa_runner.set_instance(Instance(mode="web", broadcast=True))
                    globals.kometa_runner.enqueue(asset_map)
                    return

            from utils.notifications import log_to_file, resume_log_file
            if log_file:
                # A retry runs on a fresh Timer thread. Keep the whole ladder in the file the
                # first attempt opened, the same way it keeps one history record.
                resume_log_file(log_file)
            else:
                clean_title = _clean_title(event.title)
                normalized_title = normalize_title(clean_title).replace(" ", "_")
                log_label = f"webhook_{normalized_title}_{event.year}" if event.year else f"webhook_{normalized_title}"
                log_file = log_to_file(log_label)

            # Fallback to TPDb user artwork pipeline
            if artwork is None:
                artwork = self._collect_artwork(event)
                if not artwork:
                    _log(f"📥 Webhook • {event.label} | No cached artwork from the configured users")
                    self._finish(event, key, started_at, tally, RunOutcome.SKIPPED.value)
                    return
                _log(f"📥 Webhook • {event.label} | {event.source.title()} import")
            globals.plex.connect()
            processor = UploadProcessor(globals.plex, tally)
            processor.set_options(Options())
            # allow_artist_updates is a scheduled-scrape concern and must never apply here.
            # set_options resolves it from the global config, so a bare Options() still inherits it.
            # Radarr and Sonarr send "Download" on an upgrade as well as a first import, so the item
            # this runs against may already carry artwork the user locked. The webhook also picks its
            # artists from its own configured list rather than from the scrape, so letting it replace
            # a locked field would re-sort artwork nobody asked it to touch.
            processor.allow_artist_updates = False
            pending = []
            for item in artwork:
                try:
                    _debug(f"Processing webhook item {item}")
                    if event.kind == "movie":
                        processor.process_movie_artwork(item)
                    else:
                        processor.process_tv_artwork(item)
                    # A season/episode whose show is in Plex but which Plex has not scanned in yet
                    # comes back as a "not available" result rather than an exception; treat that
                    # the same as not-found so it retries once Plex catches up.
                    if tally.unavailable_counter[0] > 0:
                        tally.unavailable_counter[0] = 0
                        pending.append(item)

                except (MovieNotFound, ShowNotFound):
                    pending.append(item)          # not in Plex yet, retry it
                except Exception as error:
                    tally.failed(1)
                    _log(f"❌ Webhook • {event.label} | {error}")
            if pending and attempt < len(WEBHOOK_RETRY_DELAYS):
                delay = WEBHOOK_RETRY_DELAYS[attempt]
                _debug(f"{event.label} not in Plex yet, retrying in {delay}s")
                timer = threading.Timer(
                    delay, self._attempt, args=(event, key, started_at, tally, attempt + 1, pending, log_file)
                )
                timer.daemon = True
                timer.start()
                return                            # keep the in-flight key until the chain ends
            if pending:
                _log(f"⚠️ Webhook • {event.label} | Item has not appeared in Plex, leaving it for the next scheduled run")
                # Artwork still pending when the ladder runs out never got applied, so it counts
                # against the run the same way an upload that exhausted its retries does.
                tally.failed(len(pending))
            if not tally.failed_counter[0]:
                outcome = RunOutcome.SUCCESS.value
            elif tally.success_counter[0]:
                outcome = RunOutcome.PARTIAL.value
            else:
                outcome = RunOutcome.FAILED.value
        except Exception as error:
            _debug(f"Webhook apply failed for {event.label}: {error}")
            outcome = RunOutcome.FAILED.value
        self._finish(event, key, started_at, tally, outcome)

    def _resolve_staged_artwork(self, event: WebhookEvent) -> Tuple[Optional[dict], bool]:
        """Check Plex and the Kometa asset directory for staged artwork matching `event`.
           Returns (asset_map, not_ready):
             - (None, True) when the show or target episode(s) have not landed in Plex yet.
             - (asset_map, False) when staged assets exist and are ready for KometaRunner.
             - ({}, False) when the item is in Plex but has no staged assets on disk."""
        import os
        from plexapi.exceptions import NotFound
        from utils.utils import get_path_parts, normalize_path

        if not event.tmdb_id:
            _debug("Webhook payload did not contain a valid TMDb ID")
            return None, False

        base_path = "/assets" if globals.docker else globals.config.kometa_base
        found_shows = globals.plex.get_item_from_tmdb_id(tmdb_id=event.tmdb_id, media_type=MediaType.TV_SHOW.value)
        
        if not found_shows:
            # Show itself has not been scanned into Plex yet
            return None, True

        asset_map = {}
        not_ready = False

        def _has_staged_file(folder: str, match_str: str) -> bool:
            files = os.listdir(folder)
            return next((file for file in files if any(f"{match_str}{ext}" == file for ext in IMAGE_EXTENSIONS)), None)

        def _has_overlay_label(plex_item) -> bool:
            labels = [str(label) for label in plex_item.labels] if hasattr(plex_item, "labels") else []
            return KOMETA_OVERLAY_LABEL in labels
        
        for library, show in found_shows.items():
            if getattr(show, "locations", None):
                show_path = normalize_path(show.locations[0])
                asset_folder = get_path_parts(show_path)[-1]
            else:
                asset_folder = _clean_title(event.title)

            asset_path = os.path.join(base_path, library, asset_folder)

            _debug(f"Checking staged assets for {event.title} in '{library}': {asset_path}")
            if not os.path.isdir(asset_path):
                continue

            library_entries = {}

            for s_num, e_num in sorted(event.episodes):
                season_prefix = f"Season{s_num:02}"
                if e_num == 1 and not event.is_upgrade: # If it's episode 1 and it's new, it means the season is also new
                    s_staged_file = _has_staged_file(asset_path, season_prefix)
                    if s_staged_file:
                        _debug(f"Found staged season cover: {s_staged_file}")
                        try:
                            _season = show.season(s_num)
                        except NotFound:
                            _debug(f"{event.title} Season {s_num} not found in library '{library}' yet")
                            not_ready = True
                            continue
                        has_overlay = _has_overlay_label(_season)
                        library_entries[_season.ratingKey] = {
                            "title": event.title,
                            "year": event.year,
                            "media_type": MediaType.TV_SHOW.value,
                            "updated_assets": [{
                                "file_type": FileType.SEASON_COVER.value,
                                "author": None,
                                "season": s_num,
                                "episode": "Cover",
                                "status": "new",
                                "overlay": has_overlay
                            }]
                        }
                    else:
                        _debug(f"There are no staged assets for {event.title} Season {s_num} for library '{library}'")

                ep_prefix = f"S{s_num:02}E{e_num:02}"
                e_staged_file = _has_staged_file(asset_path, ep_prefix)
                if e_staged_file:
                    _debug(f"Found staged episode title card: {e_staged_file}")
                    try:
                        _episode = show.episode(season=s_num, episode=e_num)
                    except NotFound:
                        _debug(f"{event.title} {ep_prefix} not found in library '{library}' yet")
                        not_ready = True
                        continue
                    has_overlay = _has_overlay_label(_episode)
                    if not event.is_upgrade or has_overlay:
                        library_entries[_episode.ratingKey] = {
                            "title": event.title,
                            "year": event.year,
                            "media_type": MediaType.TV_SHOW.value,
                            "updated_assets": [{
                                "file_type": FileType.TITLE_CARD.value,
                                "author": None,
                                "season": s_num,
                                "episode": e_num,
                                "status": "updated" if event.is_upgrade else "new",
                                "overlay": has_overlay
                            }]
                        }
                    else:
                        _debug(f"Sonarr import is an upgrade and episode {ep_prefix} has no overlay, no need to reapply artwork")
                else:
                    _debug(f"There are no staged assets for {event.title} {ep_prefix} for library '{library}'")

            if library_entries:
                asset_map[library] = library_entries

        return asset_map, not_ready

    def _finish(self, event: WebhookEvent, key, started_at: str,
                tally: ProcessingCallbacks, outcome: str) -> None:
        """Record the run and let the next event for this title through."""
        try:
            RunHistory().add_run(
                run_type=RunType.WEBHOOK.value,
                label=event.label,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc).isoformat(),
                trigger=_TRIGGER_BY_SOURCE.get(event.source, event.source),
                outcome=outcome,
                assets_processed=tally.assets_processed[0],
                success_count=tally.success_counter[0],
                cached_count=0,
                locked_count=tally.locked_counter[0],
                error_count=tally.failed_counter[0]
            )
            # Nothing else tells an open History tab that this happened. A scrape and a
            # bulk import both end with a scrape_state broadcast the browser reacts to;
            # an import applied in the background raises no such event.
        except Exception as error:
            # A history write must never cost an in-flight key, which would deadlock every
            # future import of this title behind the dedupe guard.
            _debug(f"Could not record the webhook run for {event.label}: {error}")
        self._release(key)
        if tally.updated_asset_map and globals.config.kometa_auto_run:
            _debug(f"Enqueueing {len(tally.updated_asset_map)} libraries for targeted Kometa update...")
            globals.kometa_runner.set_instance(Instance(mode='web', broadcast=True))
            globals.kometa_runner.enqueue(tally.updated_asset_map)

    def _collect_artwork(self, event: WebhookEvent) -> List[dict]:
        """Build the artwork dicts to apply by looking the title up in the index for each
           configured user, in preference order. Empty when nobody covers it."""
        user_keys = [user.strip().casefold() for user in (globals.config.webhook_tpdb_users or []) if user.strip()]
        if not user_keys:
            return []
        index = AssetIndex()
        cache_buster = f"&_cb={int(time.time())}"
        artwork: List[dict] = []
        if event.kind == "movie":
            row = index.lookup(user_keys, event.title, event.year, [FileType.MOVIE_POSTER.value])
            if row:
                poster = self._artwork_dict(row, cache_buster, FileType.MOVIE_POSTER.value)
                if event.media_folder:
                    # An edition in its own folder is a second Plex item with the same title, year
                    # and TMDb ID. The imported path tells the lookup which item the event is about.
                    poster["media_folder"] = event.media_folder
                    poster["media_file"] = event.media_file
                artwork.append(poster)
        else:
            row = index.lookup(user_keys, event.title, event.year, [FileType.SHOW_COVER.value])
            if row:
                artwork.append(self._artwork_dict(row, cache_buster, FileType.SHOW_COVER.value))
            for season in sorted(event.seasons):
                season_row = index.lookup(user_keys, event.title, event.year, [FileType.SEASON_COVER.value], season=season)
                if season_row:
                    artwork.append(self._artwork_dict(season_row, cache_buster, FileType.SEASON_COVER.value, season))
        return artwork

    @staticmethod
    def _artwork_dict(row, cache_buster: str, artwork_type: str, season=None) -> dict:
        """Build a get_posters-shaped artwork dict from an index row. tmdb_id stays None so the
           processor resolves identity authoritatively from the poster page at write time. The
           artwork type MUST be keyed as 'file_type' - the key get_posters writes and the upload
           processor reads to resolve the Plex label prefix; 'type' leaves it unresolved and the
           uploader crashes on None + md5."""
        artwork = {
            "title": row["title"],
            "author": row["author"],
            "tmdb_id": None,
            "url": f"{row['url']}{cache_buster}",
            "year": row["year"],
            "source": ScraperSource.THEPOSTERDB.value,
            "id": str(row["asset_id"]),
            "file_type": artwork_type,
        }
        if artwork_type in (FileType.SHOW_COVER.value, FileType.SEASON_COVER.value):
            artwork["season"] = "Cover" if artwork_type == FileType.SHOW_COVER.value else season
            artwork["episode"] = None
        return artwork
