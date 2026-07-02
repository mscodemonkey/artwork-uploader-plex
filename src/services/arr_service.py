"""
Radarr/Sonarr integration used to pre-seed Kometa artwork before media lands in Plex.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from core.config import Config
from utils.notifications import debug_me
from utils.utils import get_path_parts

CACHE_TTL_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 10


def _normalize_title(title: Optional[str]) -> str:
    if not title:
        return ""
    return re.sub(r"[^a-z0-9]", "", title.casefold())


def _folder_name(path: Optional[str]) -> Optional[str]:
    parts = get_path_parts(path)
    return parts[-1] if parts else None


@dataclass
class ArrMovie:
    folder_name: str
    root_folder_path: Optional[str]
    title: str
    year: Optional[int]


@dataclass
class ArrSeries:
    folder_name: str
    root_folder_path: Optional[str]
    title: str
    year: Optional[int]
    season_numbers: set = field(default_factory=set)


class ArrClient:
    """Base client for the shared parts of the Radarr/Sonarr v3 REST API."""

    def __init__(self, base_url: Optional[str], api_key: Optional[str]) -> None:
        self.base_url: str = (base_url or "").rstrip("/")
        self.api_key: str = api_key or ""
        self._cache: Optional[list] = None
        self._cache_time: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _get(self, endpoint: str, params: Optional[dict] = None) -> Optional[list]:
        if not self.configured:
            return None
        url = f"{self.base_url}/api/v3/{endpoint}"
        try:
            response = requests.get(
                url,
                headers={"X-Api-Key": self.api_key},
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            debug_me(f"Request to '{url}' failed: {e}",
                     f"{type(self).__name__}/_get")
            return None

    def _cached_list(self, endpoint: str) -> list:
        now = time.monotonic()
        if self._cache is None or (now - self._cache_time) > CACHE_TTL_SECONDS:
            result = self._get(endpoint)
            self._cache = result if isinstance(result, list) else []
            self._cache_time = now
        return self._cache

    def clear_cache(self) -> None:
        self._cache = None
        self._cache_time = 0.0


class RadarrClient(ArrClient):

    def find_movie(
            self, tmdb_id: Optional[int], title: Optional[str],
            year: Optional[int]) -> Optional[ArrMovie]:
        if not self.configured:
            return None

        if tmdb_id:
            result = self._get("movie", params={"tmdbId": tmdb_id})
            if not result:
                return None
            movies = result if isinstance(result, list) else [result]
            matches = [m for m in movies if m.get("tmdbId") == tmdb_id]
            if len(matches) == 1:
                return self._to_arr_movie(matches[0])
            if len(matches) > 1:
                debug_me(
                    f"Ambiguous Radarr tmdbId match for '{tmdb_id}': {len(matches)} candidates",
                    "RadarrClient/find_movie",
                )
            return None

        if not title:
            return None

        normalized_title = _normalize_title(title)
        candidates = []
        for movie in self._cached_list("movie"):
            if _normalize_title(movie.get("title")) != normalized_title:
                continue
            movie_year = movie.get("year")
            if year is not None and movie_year is not None and abs(int(movie_year) - int(year)) > 1:
                continue
            candidates.append(movie)

        if len(candidates) == 1:
            return self._to_arr_movie(candidates[0])
        if len(candidates) > 1:
            debug_me(
                f"Ambiguous Radarr title match for '{title} ({year})': {len(candidates)} candidates",
                "RadarrClient/find_movie",
            )
        return None

    @staticmethod
    def _to_arr_movie(movie: dict) -> Optional[ArrMovie]:
        folder_name = _folder_name(movie.get("path"))
        if not folder_name:
            return None
        return ArrMovie(
            folder_name=folder_name,
            root_folder_path=movie.get("rootFolderPath"),
            title=movie.get("title", ""),
            year=movie.get("year"),
        )


class SonarrClient(ArrClient):

    def find_series(
            self, tmdb_id: Optional[int], title: Optional[str],
            year: Optional[int]) -> Optional[ArrSeries]:
        if not self.configured:
            return None

        series_list = self._cached_list("series")

        if tmdb_id:
            matches = [s for s in series_list if s.get("tmdbId") == tmdb_id]
            if len(matches) == 1:
                return self._to_arr_series(matches[0])
            if len(matches) > 1:
                debug_me(
                    f"Ambiguous Sonarr tmdbId match for '{tmdb_id}': {len(matches)} candidates",
                    "SonarrClient/find_series",
                )
                return None

        if not title:
            return None

        normalized_title = _normalize_title(title)
        candidates = []
        for series in series_list:
            names = [series.get("title"), series.get("sortTitle")]
            names.extend(
                alt.get("title") for alt in series.get("alternateTitles", []) if isinstance(alt, dict)
            )
            if not any(_normalize_title(name) == normalized_title for name in names if name):
                continue
            series_year = series.get("year")
            if year is not None and series_year is not None and abs(int(series_year) - int(year)) > 1:
                continue
            candidates.append(series)

        if len(candidates) == 1:
            return self._to_arr_series(candidates[0])
        if len(candidates) > 1:
            debug_me(
                f"Ambiguous Sonarr title match for '{title} ({year})': {len(candidates)} candidates",
                "SonarrClient/find_series",
            )
        return None

    @staticmethod
    def _to_arr_series(series: dict) -> Optional[ArrSeries]:
        folder_name = _folder_name(series.get("path"))
        if not folder_name:
            return None
        season_numbers = {
            s.get("seasonNumber")
            for s in series.get("seasons", [])
            if isinstance(s.get("seasonNumber"), int)
        }
        return ArrSeries(
            folder_name=folder_name,
            root_folder_path=series.get("rootFolderPath"),
            title=series.get("title", ""),
            year=series.get("year"),
            season_numbers=season_numbers,
        )


class ArrService:
    """Facade wiring RadarrClient/SonarrClient to the application config."""

    def __init__(self, config: Config) -> None:
        self.radarr: RadarrClient = RadarrClient(
            config.radarr_url, config.radarr_api_key)
        self.sonarr: SonarrClient = SonarrClient(
            config.sonarr_url, config.sonarr_api_key)
        self.preseed_arr: bool = config.preseed_arr

    def reconfigure(self, config: Config) -> None:
        self.radarr = RadarrClient(config.radarr_url, config.radarr_api_key)
        self.sonarr = SonarrClient(config.sonarr_url, config.sonarr_api_key)
        self.preseed_arr = config.preseed_arr

    @property
    def movie_fallback_enabled(self) -> bool:
        return self.preseed_arr and self.radarr.configured

    @property
    def tv_fallback_enabled(self) -> bool:
        return self.preseed_arr and self.sonarr.configured
