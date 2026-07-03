"""
In-tool Sonarr/Radarr import webhook.

On a Radarr/Sonarr "Download" (import) event, look the imported title up in the persistent
asset index and apply the cached poster through the normal upload path, retrying for a few
minutes while Plex finishes scanning the new file. Everything downstream of the dispatch (the
authoritative TMDb resolution, artwork-ID skips, locked-artwork skips, Kometa mode) is the same
code a normal scrape uses, so the webhook inherits all of it without re-implementing any of it.
"""

import threading
import time
from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Union

from core import globals
from core.constants import WEBHOOK_RETRY_DELAYS
from core.enums import ScraperSource
from core.exceptions import MovieNotFound, ShowNotFound
from models.instance import Instance
from models.options import Options
from services.asset_index import AssetIndex, normalize_title


def _log(text: str) -> None:
    # utils.notifications imports the services package, so import it lazily to avoid an import
    # cycle when the services package pulls this module in at start-up.
    from utils.notifications import update_log
    update_log(Instance(broadcast=True), text)


def _debug(message: str) -> None:
    from utils.notifications import debug_me
    debug_me(message, "WebhookService")


@dataclass(frozen=True)
class WebhookEvent:
    """A parsed Sonarr/Radarr import event."""
    kind: str                      # "movie" or "tv"
    title: str
    year: Optional[int]
    tmdb_id: Optional[int]
    tvdb_id: Optional[int]
    seasons: FrozenSet[int]
    source: str                    # "radarr" or "sonarr"

    def label(self) -> str:
        return f"{self.title} ({self.year})" if self.year else self.title


def _int_or_none(value) -> Optional[int]:
    """Map absent numeric fields to None. Radarr/Sonarr serialise absent ints and years as 0
       (C# defaults), so 0 is treated as absent. NOT used for season numbers, where 0 (Specials)
       is a real value."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number or None


def parse_event(payload: dict) -> Union[WebhookEvent, str, None]:
    """Parse a Radarr/Sonarr webhook payload.

       Returns a WebhookEvent for an import ("Download") event, the string "test" for the
       connection Test button, or None for any other event type or malformed payload. Never
       raises, so an unexpected payload is acknowledged and ignored rather than erroring."""
    if not isinstance(payload, dict):
        return None
    event_type = payload.get("eventType")
    if event_type == "Test":
        return "test"
    if event_type != "Download":
        return None
    movie = payload.get("movie")
    if isinstance(movie, dict) and movie.get("title"):
        return WebhookEvent(
            kind="movie", title=movie["title"], year=_int_or_none(movie.get("year")),
            tmdb_id=_int_or_none(movie.get("tmdbId")), tvdb_id=None,
            seasons=frozenset(), source="radarr",
        )
    series = payload.get("series")
    if isinstance(series, dict) and series.get("title"):
        episodes = payload.get("episodes") or []
        seasons = frozenset(
            episode["seasonNumber"] for episode in episodes
            if isinstance(episode, dict) and isinstance(episode.get("seasonNumber"), int)
        )
        return WebhookEvent(
            kind="tv", title=series["title"], year=_int_or_none(series.get("year")),
            tmdb_id=_int_or_none(series.get("tmdbId")), tvdb_id=_int_or_none(series.get("tvdbId")),
            seasons=seasons, source="sonarr",
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
                _debug(f"Import for {event.label()} is already pending, ignoring the duplicate")
                return
            self._inflight.add(key)
        # Wait a configurable delay before the first attempt: the *arr apps fire the webhook the
        # moment they import a file, usually before Plex has scanned it in, so give Plex a head
        # start. If it is still not ready by then, the retry ladder takes over.
        delay = max(0, globals.config.webhook_apply_delay or 0)
        timer = threading.Timer(delay, self._attempt, args=(event, key))
        timer.daemon = True
        timer.start()

    @staticmethod
    def _dedupe_key(event: WebhookEvent):
        identity = event.tmdb_id or event.tvdb_id or normalize_title(event.title)
        return (event.kind, identity, event.seasons)

    def _release(self, key) -> None:
        with self._lock:
            self._inflight.discard(key)

    def _attempt(self, event: WebhookEvent, key, attempt: int = 0,
                 artwork: Optional[List[dict]] = None) -> None:
        # UploadProcessor pulls in the processors -> plex chain; import it here so the services
        # package does not drag that in at start-up (mirrors the app's own lazy-import pattern).
        from processors.upload_processor import UploadProcessor
        try:
            if artwork is None:
                artwork = self._collect_artwork(event)
                if not artwork:
                    _log(f"📥 Webhook | No cached artwork for '{event.label()}' from the configured users")
                    self._release(key)
                    return
                _log(f"📥 Webhook | {event.source.title()} import: {event.label()}")
            globals.plex.connect()
            processor = UploadProcessor(globals.plex)
            processor.set_options(Options())
            pending = []
            for item in artwork:
                try:
                    if event.kind == "movie":
                        results = processor.process_movie_artwork(item)
                    else:
                        results = processor.process_tv_artwork(item)
                    results = results or []
                    # A season/episode whose show is in Plex but which Plex has not scanned in yet
                    # comes back as a "not available" result rather than an exception; treat that
                    # the same as not-found so it retries once Plex catches up.
                    if any("not available" in str(result).lower() for result in results):
                        pending.append(item)
                    else:
                        for result in results:
                            _log(result)
                except (MovieNotFound, ShowNotFound):
                    pending.append(item)          # not in Plex yet, retry it
                except Exception as error:
                    _log(f"❌ Webhook | {event.label()}: {error}")
            if pending and attempt < len(WEBHOOK_RETRY_DELAYS):
                delay = WEBHOOK_RETRY_DELAYS[attempt]
                _debug(f"{event.label()} not in Plex yet, retrying in {delay}s")
                timer = threading.Timer(delay, self._attempt, args=(event, key, attempt + 1, pending))
                timer.daemon = True
                timer.start()
                return                            # keep the in-flight key until the chain ends
            if pending:
                _log(f"⚠️ Webhook | '{event.label()}' has not appeared in Plex, leaving it for the next scheduled run")
        except Exception as error:
            _debug(f"Webhook apply failed for {event.label()}: {error}")
        self._release(key)

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
            row = index.lookup(user_keys, event.title, event.year, ["movie_poster"])
            if row:
                artwork.append(self._artwork_dict(row, cache_buster, "movie_poster"))
        else:
            row = index.lookup(user_keys, event.title, event.year, ["show_cover"])
            if row:
                artwork.append(self._artwork_dict(row, cache_buster, "show_cover"))
            for season in sorted(event.seasons):
                season_row = index.lookup(user_keys, event.title, event.year, ["season_cover"], season=season)
                if season_row:
                    artwork.append(self._artwork_dict(season_row, cache_buster, "season_cover", season))
        return artwork

    @staticmethod
    def _artwork_dict(row, cache_buster: str, artwork_type: str, season=None) -> dict:
        """Build a get_posters-shaped artwork dict from an index row. tmdb_id stays None so the
           processor resolves identity authoritatively from the poster page at write time."""
        artwork = {
            "title": row["title"],
            "author": row["author"],
            "tmdb_id": None,
            "url": f"{row['url']}{cache_buster}",
            "year": row["year"],
            "source": ScraperSource.THEPOSTERDB.value,
            "id": str(row["asset_id"]),
            "type": artwork_type,
        }
        if artwork_type in ("show_cover", "season_cover"):
            artwork["season"] = "Cover" if artwork_type == "show_cover" else season
            artwork["episode"] = None
        return artwork
