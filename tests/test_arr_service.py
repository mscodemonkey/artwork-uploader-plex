from unittest.mock import MagicMock

import pytest
import requests

from core.config import Config
from services.arr_service import ArrService, RadarrClient, SonarrClient

pytestmark = pytest.mark.unit


def _response(json_value=None, status_code=200, raise_exc=None):
    response = MagicMock()
    if raise_exc is not None:
        response.raise_for_status.side_effect = raise_exc
    else:
        response.raise_for_status.return_value = None
    response.status_code = status_code
    if isinstance(json_value, Exception):
        response.json.side_effect = json_value
    else:
        response.json.return_value = json_value
    return response


@pytest.fixture
def radarr():
    return RadarrClient("http://localhost:7878", "radarr-key")


@pytest.fixture
def sonarr():
    return SonarrClient("http://localhost:8989", "sonarr-key")


class TestArrClientConfigured:

    def test_not_configured_without_url_or_key(self):
        assert not RadarrClient("", "key").configured
        assert not RadarrClient("http://localhost:7878", "").configured
        assert not RadarrClient("", "").configured

    def test_configured_with_url_and_key(self, radarr):
        assert radarr.configured

    def test_find_movie_returns_none_when_not_configured(self):
        client = RadarrClient("", "")
        assert client.find_movie(603, "The Matrix", 1999) is None


class TestRadarrFindMovie:

    def test_tmdb_id_match_with_path(self, radarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"tmdbId": 603, "title": "The Matrix", "year": 1999,
             "path": "/data/media/movies/The Matrix (1999)",
             "rootFolderPath": "/data/media/movies"}
        ])
        result = radarr.find_movie(603, "The Matrix", 1999)
        assert result is not None
        assert result.folder_name == "The Matrix (1999)"
        assert result.root_folder_path == "/data/media/movies"
        get.assert_called_once()
        assert get.call_args.kwargs["params"] == {"tmdbId": 603}

    def test_tmdb_id_no_match_does_not_fall_back_to_title(self, radarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([])
        result = radarr.find_movie(603, "The Matrix", 1999)
        assert result is None
        get.assert_called_once()

    def test_tmdb_id_response_mismatch_is_rejected(self, radarr, mocker):
        # Some Radarr deployments ignore the tmdbId query param and return the
        # full catalog; the first hit must not be trusted without checking tmdbId.
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"tmdbId": 999, "title": "Some Other Movie", "year": 2001,
             "path": "/data/media/movies/Some Other Movie (2001)",
             "rootFolderPath": "/data/media/movies"}
        ])
        result = radarr.find_movie(603, "The Matrix", 1999)
        assert result is None

    def test_tmdb_id_multiple_matches_returns_none(self, radarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"tmdbId": 603, "title": "The Matrix", "year": 1999,
             "path": "/data/media/movies/The Matrix (1999)",
             "rootFolderPath": "/data/media/movies"},
            {"tmdbId": 603, "title": "The Matrix Duplicate", "year": 1999,
             "path": "/data/media/movies/The Matrix Duplicate (1999)",
             "rootFolderPath": "/data/media/movies"},
        ])
        result = radarr.find_movie(603, "The Matrix", 1999)
        assert result is None

    def test_tmdb_id_match_without_path_is_skipped(self, radarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([{"title": "The Matrix", "year": 1999}])
        assert radarr.find_movie(603, "The Matrix", 1999) is None

    def test_title_year_fallback_single_match(self, radarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "The Matrix", "year": 1999, "path": "/data/media/movies/The Matrix (1999)",
             "rootFolderPath": "/data/media/movies"},
            {"title": "Unrelated Movie", "year": 2010, "path": "/data/media/movies/Unrelated (2010)",
             "rootFolderPath": "/data/media/movies"},
        ])
        result = radarr.find_movie(None, "The Matrix", 1999)
        assert result is not None
        assert result.folder_name == "The Matrix (1999)"

    def test_title_year_fallback_tolerates_one_year_drift(self, radarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "The Matrix", "year": 2000, "path": "/data/media/movies/The Matrix (2000)",
             "rootFolderPath": "/data/media/movies"},
        ])
        result = radarr.find_movie(None, "The Matrix", 1999)
        assert result is not None

    def test_title_year_fallback_rejects_two_year_drift(self, radarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "The Matrix", "year": 2001, "path": "/data/media/movies/The Matrix (2001)",
             "rootFolderPath": "/data/media/movies"},
        ])
        assert radarr.find_movie(None, "The Matrix", 1999) is None

    def test_ambiguous_title_match_returns_none(self, radarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "The Matrix", "year": 1999, "path": "/data/movies-a/The Matrix (1999)",
             "rootFolderPath": "/data/movies-a"},
            {"title": "The Matrix", "year": 1999, "path": "/data/movies-b/The Matrix (1999)",
             "rootFolderPath": "/data/movies-b"},
        ])
        assert radarr.find_movie(None, "The Matrix", 1999) is None

    def test_no_title_no_tmdb_id_returns_none(self, radarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        assert radarr.find_movie(None, None, 1999) is None
        get.assert_not_called()

    def test_timeout_returns_none(self, radarr, mocker):
        mocker.patch("services.arr_service.requests.get", side_effect=requests.exceptions.Timeout())
        assert radarr.find_movie(603, "The Matrix", 1999) is None

    def test_unauthorized_returns_none(self, radarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response(status_code=401, raise_exc=requests.exceptions.HTTPError())
        assert radarr.find_movie(603, "The Matrix", 1999) is None

    def test_bad_json_returns_none(self, radarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response(json_value=ValueError("bad json"))
        assert radarr.find_movie(603, "The Matrix", 1999) is None


class TestSonarrFindSeries:

    def test_tmdb_id_single_match(self, sonarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "Breaking Bad", "year": 2008, "tmdbId": 1396,
             "path": "/data/media/tv/Breaking Bad (2008)", "rootFolderPath": "/data/media/tv",
             "seasons": [{"seasonNumber": 0, "monitored": False}, {"seasonNumber": 1, "monitored": True}]},
        ])
        result = sonarr.find_series(1396, "Breaking Bad", 2008)
        assert result is not None
        assert result.folder_name == "Breaking Bad (2008)"
        assert result.season_numbers == {0, 1}

    def test_tmdb_id_ambiguous_does_not_fall_back(self, sonarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "Show A", "year": 2008, "tmdbId": 1396, "path": "/data/tv/Show A", "rootFolderPath": "/data/tv"},
            {"title": "Show B", "year": 2009, "tmdbId": 1396, "path": "/data/tv/Show B", "rootFolderPath": "/data/tv"},
        ])
        assert sonarr.find_series(1396, "Show A", 2008) is None

    def test_tmdb_id_no_match_falls_back_to_title(self, sonarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "Breaking Bad", "year": 2008, "path": "/data/media/tv/Breaking Bad (2008)",
             "rootFolderPath": "/data/media/tv", "seasons": []},
        ])
        result = sonarr.find_series(9999, "Breaking Bad", 2008)
        assert result is not None
        assert result.folder_name == "Breaking Bad (2008)"

    def test_alternate_titles_match(self, sonarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "Foreign Title", "year": 2020, "path": "/data/media/tv/Foreign (2020)",
             "rootFolderPath": "/data/media/tv", "seasons": [],
             "alternateTitles": [{"title": "English Title"}]},
        ])
        result = sonarr.find_series(None, "English Title", 2020)
        assert result is not None
        assert result.folder_name == "Foreign (2020)"

    def test_ambiguous_title_match_returns_none(self, sonarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "Show", "year": 2020, "path": "/data/tv-a/Show", "rootFolderPath": "/data/tv-a", "seasons": []},
            {"title": "Show", "year": 2020, "path": "/data/tv-b/Show", "rootFolderPath": "/data/tv-b", "seasons": []},
        ])
        assert sonarr.find_series(None, "Show", 2020) is None

    def test_windows_style_path_folder_extraction(self, sonarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "Breaking Bad", "year": 2008, "tmdbId": 1396,
             "path": r"C:\data\media\tv\Breaking Bad (2008)", "rootFolderPath": r"C:\data\media\tv",
             "seasons": []},
        ])
        result = sonarr.find_series(1396, "Breaking Bad", 2008)
        assert result.folder_name == "Breaking Bad (2008)"

    def test_series_without_path_is_skipped(self, sonarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "Breaking Bad", "year": 2008, "tmdbId": 1396, "seasons": []},
        ])
        assert sonarr.find_series(1396, "Breaking Bad", 2008) is None


class TestCaching:

    def test_repeated_lookups_reuse_cached_list(self, sonarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "Breaking Bad", "year": 2008, "path": "/data/tv/Breaking Bad (2008)",
             "rootFolderPath": "/data/tv", "seasons": []},
        ])
        sonarr.find_series(None, "Breaking Bad", 2008)
        sonarr.find_series(None, "Breaking Bad", 2008)
        assert get.call_count == 1

    def test_clear_cache_forces_refetch(self, sonarr, mocker):
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([])
        sonarr.find_series(None, "Breaking Bad", 2008)
        sonarr.clear_cache()
        sonarr.find_series(None, "Breaking Bad", 2008)
        assert get.call_count == 2


class TestArrService:

    def _config(self):
        config = Config.__new__(Config)
        config.radarr_url = "http://localhost:7878"
        config.radarr_api_key = "radarr-key"
        config.sonarr_url = ""
        config.sonarr_api_key = ""
        config.preseed_arr = True
        return config

    def test_movie_fallback_enabled_requires_preseed_and_configured_client(self):
        config = self._config()
        service = ArrService(config)
        assert service.movie_fallback_enabled is True
        assert service.tv_fallback_enabled is False

    def test_disabled_when_preseed_arr_is_false(self):
        config = self._config()
        config.preseed_arr = False
        service = ArrService(config)
        assert service.movie_fallback_enabled is False

    def test_reconfigure_rebuilds_clients_and_drops_cache(self, mocker):
        config = self._config()
        service = ArrService(config)
        get = mocker.patch("services.arr_service.requests.get")
        get.return_value = _response([
            {"title": "Foo", "year": 2020, "path": "/data/movies/Foo (2020)", "rootFolderPath": "/data/movies"}
        ])
        service.radarr.find_movie(None, "Foo", 2020)
        assert get.call_count == 1

        new_config = self._config()
        new_config.radarr_url = "http://localhost:9999"
        service.reconfigure(new_config)
        assert service.radarr.base_url == "http://localhost:9999"

        service.radarr.find_movie(None, "Foo", 2020)
        # A fresh client means a fresh (empty) cache, so this triggers another request.
        assert get.call_count == 2
