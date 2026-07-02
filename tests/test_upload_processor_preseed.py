from types import SimpleNamespace

import pytest
from plexapi.exceptions import NotFound

from core import globals
from core.config import Config
from core.exceptions import (MovieNotFound, NotProcessedByExclusion,
                             NotProcessedByFilter, ShowNotFound)
from kometa.kometa_saver import KometaSaver
from models.options import Options
from processors.upload_processor import UploadProcessor
from services.arr_service import ArrMovie, ArrSeries

pytestmark = pytest.mark.unit


class FakePlex:
    """Stub PlexConnector: find_in_library always reports 'not found' unless overridden."""

    def __init__(self, items=None, libraries=None):
        self._items = items
        self._libraries = libraries

    def find_in_library(self, item_type, artwork):
        return self._items, self._libraries


class FakeRadarr:
    def __init__(self, movie=None):
        self._movie = movie

    def find_movie(self, tmdb_id, title, year):
        return self._movie


class FakeSonarr:
    def __init__(self, series=None):
        self._series = series

    def find_series(self, tmdb_id, title, year):
        return self._series


class FakeArr:
    def __init__(self, radarr=None, sonarr=None, movie_enabled=True, tv_enabled=True):
        self.radarr = radarr or FakeRadarr()
        self.sonarr = sonarr or FakeSonarr()
        self.movie_fallback_enabled = movie_enabled
        self.tv_fallback_enabled = tv_enabled


def _movie_artwork(**overrides):
    artwork = {
        "title": "The Matrix", "url": "http://example.com/poster.jpg", "year": 1999,
        "source": "mediux", "id": "poster-1", "type": "movie_poster", "author": "someone",
        "tmdb_id": 603,
    }
    artwork.update(overrides)
    return artwork


def _tv_artwork(**overrides):
    artwork = {
        "title": "Breaking Bad", "url": "http://example.com/season.jpg", "season": 1,
        "episode": None, "year": 2008, "source": "mediux", "id": "season-1",
        "type": "season_cover", "author": "someone", "tmdb_id": 1396,
    }
    artwork.update(overrides)
    return artwork


def _arr_movie(
        folder_name="The Matrix (1999)", root_folder_path="/data/media/movies",
        title="The Matrix", year=1999):
    return ArrMovie(folder_name=folder_name, root_folder_path=root_folder_path, title=title, year=year)


def _arr_series(
        folder_name="Breaking Bad (2008)", root_folder_path="/data/media/tv",
        title="Breaking Bad", year=2008, season_numbers=()):
    return ArrSeries(
        folder_name=folder_name, root_folder_path=root_folder_path, title=title, year=year,
        season_numbers=set(season_numbers))


class FakeEpisode:
    def __init__(self, index, file_path):
        self.index = index
        self.media = [SimpleNamespace(parts=[SimpleNamespace(file=file_path)])]


class FakeSeason:
    def __init__(self, index, episodes):
        self.index = index
        self._episodes = episodes

    def episodes(self):
        return self._episodes


class FakeShow:
    def __init__(self, title, seasons):
        self.title = title
        self._seasons = seasons

    def seasons(self):
        return self._seasons

    def season(self, number):
        for s in self._seasons:
            if s.index == number:
                return s
        raise NotFound(f"season {number} not found")


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = Config()
    cfg.load()
    cfg.kometa_base = str(tmp_path / "assets")
    cfg.save_to_kometa = True
    cfg.preseed_arr = True
    cfg.movie_library = ["Movies"]
    cfg.tv_library = ["TV Shows"]
    cfg.stage_assets = False
    cfg.stage_specials = False
    cfg.arr_root_folder_library_map = {}
    cfg.save()
    globals.config = cfg
    globals.debug = False
    return cfg


@pytest.fixture
def capture_kometa_saves(monkeypatch):
    calls = []

    def fake_save(self):
        calls.append({
            "dest_dir": self.dest_dir,
            "dest_file_name": self.dest_file_name,
            "description": self.description,
            "library": self.library,
            "artwork_type": self.artwork_type,
        })
        return f"✅ {self.description} | {self.artwork_type} saved (fake)"

    monkeypatch.setattr(KometaSaver, "save_to_kometa", fake_save)
    return calls


def _processor(configured, arr, options=None):
    proc = UploadProcessor(FakePlex(items=None, libraries=None), arr=arr)
    proc.set_options(options or Options(kometa=True))
    return proc


class TestMoviePreseed:

    def test_happy_path_saves_under_radarr_folder(self, configured, capture_kometa_saves):
        arr_movie = _arr_movie()
        arr = FakeArr(radarr=FakeRadarr(movie=arr_movie))
        proc = _processor(configured, arr)

        results = proc.process_movie_artwork(_movie_artwork())

        assert len(results) == 1
        assert results[0].startswith("✅")
        assert len(capture_kometa_saves) == 1
        call = capture_kometa_saves[0]
        assert call["library"] == "Movies"
        assert call["dest_dir"].endswith("/assets/Movies/The Matrix (1999)")
        assert "pre-seeded via Radarr" in call["description"]

    def test_not_in_radarr_raises_movie_not_found_mentioning_radarr(self, configured, capture_kometa_saves):
        arr = FakeArr(radarr=FakeRadarr(movie=None))
        proc = _processor(configured, arr)

        with pytest.raises(MovieNotFound) as exc_info:
            proc.process_movie_artwork(_movie_artwork())

        assert "Radarr" in str(exc_info.value)
        assert not capture_kometa_saves

    def test_arr_fallback_disabled_uses_original_message(self, configured, capture_kometa_saves):
        arr = FakeArr(radarr=FakeRadarr(movie=None), movie_enabled=False)
        proc = _processor(configured, arr)

        with pytest.raises(MovieNotFound) as exc_info:
            proc.process_movie_artwork(_movie_artwork())

        assert "Radarr" not in str(exc_info.value)

    def test_non_kometa_mode_does_not_use_arr_fallback(self, configured, capture_kometa_saves):
        configured.save_to_kometa = False
        configured.save()
        arr_movie = _arr_movie()
        arr = FakeArr(radarr=FakeRadarr(movie=arr_movie))
        proc = _processor(configured, arr, options=Options(kometa=False))

        with pytest.raises(MovieNotFound):
            proc.process_movie_artwork(_movie_artwork())

        assert not capture_kometa_saves

    def test_excluded_artwork_raises_not_processed_by_exclusion(self, configured, capture_kometa_saves):
        arr_movie = _arr_movie()
        arr = FakeArr(radarr=FakeRadarr(movie=arr_movie))
        proc = _processor(configured, arr, options=Options(kometa=True, exclude=["poster-1"]))

        with pytest.raises(NotProcessedByExclusion):
            proc.process_movie_artwork(_movie_artwork())

    def test_filtered_artwork_raises_not_processed_by_filter(self, configured, capture_kometa_saves):
        arr_movie = _arr_movie()
        arr = FakeArr(radarr=FakeRadarr(movie=arr_movie))
        proc = _processor(configured, arr, options=Options(kometa=True, filters=["background"]))

        with pytest.raises(NotProcessedByFilter):
            proc.process_movie_artwork(_movie_artwork())

    def test_per_run_kometa_option_enables_arr_fallback_after_set_options(
            self, configured, capture_kometa_saves):
        # Global save_to_kometa is off; only the per-run --kometa option (applied via
        # set_options *after* construction) turns Kometa mode on for this run. The arr
        # fallback flags must be recomputed then, not frozen at construction time.
        configured.save_to_kometa = False
        configured.save()
        arr_movie = _arr_movie()
        arr = FakeArr(radarr=FakeRadarr(movie=arr_movie))
        proc = UploadProcessor(FakePlex(items=None, libraries=None), arr=arr)
        assert proc.kometa is False
        proc.set_options(Options(kometa=True))
        assert proc.kometa is True

        results = proc.process_movie_artwork(_movie_artwork())

        assert results[0].startswith("✅")
        assert len(capture_kometa_saves) == 1

    def test_uses_root_folder_library_map(self, configured, capture_kometa_saves):
        configured.arr_root_folder_library_map = {"/data/media/movies": "4K Movies"}
        configured.save()
        arr_movie = _arr_movie()
        arr = FakeArr(radarr=FakeRadarr(movie=arr_movie))
        proc = _processor(configured, arr)

        proc.process_movie_artwork(_movie_artwork())

        assert capture_kometa_saves[0]["library"] == "4K Movies"


class TestTvPreseed:

    def test_show_not_in_plex_or_sonarr_raises_show_not_found_mentioning_sonarr(
            self, configured, capture_kometa_saves):
        arr = FakeArr(sonarr=FakeSonarr(series=None))
        proc = _processor(configured, arr)

        with pytest.raises(ShowNotFound) as exc_info:
            proc.process_tv_artwork(_tv_artwork())

        assert "Sonarr" in str(exc_info.value)

    def test_show_in_sonarr_season_known_saves_asset(self, configured, capture_kometa_saves):
        arr_series = _arr_series(season_numbers={0, 1, 2})
        arr = FakeArr(sonarr=FakeSonarr(series=arr_series))
        proc = _processor(configured, arr)

        results = proc.process_tv_artwork(_tv_artwork(season=1, episode=None))

        assert len(results) == 1
        assert results[0].startswith("✅")
        call = capture_kometa_saves[0]
        assert call["dest_dir"].endswith("/assets/TV Shows/Breaking Bad (2008)")
        assert call["dest_file_name"] == "Season01"
        assert "pre-seeded via Sonarr" in call["description"]

    def test_season_unknown_to_sonarr_returns_warning_not_exception(self, configured, capture_kometa_saves):
        arr_series = _arr_series(season_numbers={1})
        arr = FakeArr(sonarr=FakeSonarr(series=arr_series))
        proc = _processor(configured, arr)

        results = proc.process_tv_artwork(_tv_artwork(season=5, episode=None))

        assert len(results) == 1
        assert results[0].startswith("⚠️")
        assert "not known to Sonarr" in results[0]
        assert not capture_kometa_saves

    def test_specials_blocked_without_stage_specials(self, configured, capture_kometa_saves):
        configured.stage_specials = False
        configured.save()
        arr_series = _arr_series(season_numbers={0, 1})
        arr = FakeArr(sonarr=FakeSonarr(series=arr_series))
        proc = _processor(configured, arr)

        results = proc.process_tv_artwork(_tv_artwork(season=0, episode=None))

        assert results[0].startswith("⚠️")
        assert not capture_kometa_saves

    def test_specials_allowed_with_stage_specials(self, configured, capture_kometa_saves):
        configured.stage_specials = True
        configured.save()
        arr_series = _arr_series(season_numbers={0, 1})
        arr = FakeArr(sonarr=FakeSonarr(series=arr_series))
        proc = _processor(configured, arr)

        results = proc.process_tv_artwork(_tv_artwork(season=0, episode=None))

        assert results[0].startswith("✅")

    def test_episode_title_card_saves_with_correct_file_name(self, configured, capture_kometa_saves):
        arr_series = _arr_series(season_numbers={1})
        arr = FakeArr(sonarr=FakeSonarr(series=arr_series))
        proc = _processor(configured, arr)

        results = proc.process_tv_artwork(
            _tv_artwork(season=1, episode=5, type="title_card"))

        assert results[0].startswith("✅")
        assert capture_kometa_saves[0]["dest_file_name"] == "S01E05"

    def test_arr_fallback_disabled_uses_original_show_not_found_message(self, configured, capture_kometa_saves):
        arr = FakeArr(sonarr=FakeSonarr(series=None), tv_enabled=False)
        proc = _processor(configured, arr)

        with pytest.raises(ShowNotFound) as exc_info:
            proc.process_tv_artwork(_tv_artwork())

        assert "Sonarr" not in str(exc_info.value)


class TestExistingShowMissingSeasonFromSonarr:
    """A show that already exists in Plex, but is missing a season Sonarr knows about."""

    def _plex_with_show(self):
        episode = FakeEpisode(1, "/data/media/tv/Breaking Bad (2008)/Season 01/S01E01.mkv")
        season1 = FakeSeason(1, [episode])
        show = FakeShow("Breaking Bad", [season1])
        return FakePlex(items=[show], libraries=["TV Shows"])

    def test_season_known_to_sonarr_but_missing_from_plex_is_processed(self, configured, capture_kometa_saves):
        arr_series = _arr_series(season_numbers={1, 2})
        arr = FakeArr(sonarr=FakeSonarr(series=arr_series))
        proc = UploadProcessor(self._plex_with_show(), arr=arr)
        proc.set_options(Options(kometa=True))

        results = proc.process_tv_artwork(_tv_artwork(season=2, episode=None))

        assert results[0].startswith("✅")
        assert "pre-seeded via Sonarr" in capture_kometa_saves[0]["description"]
        # Asset folder is still derived from the Plex show's existing file path.
        assert capture_kometa_saves[0]["dest_dir"].endswith("/assets/TV Shows/Breaking Bad (2008)")

    def test_season_unknown_to_sonarr_and_missing_from_plex_warns(self, configured, capture_kometa_saves):
        arr_series = _arr_series(season_numbers={1})
        arr = FakeArr(sonarr=FakeSonarr(series=arr_series))
        proc = UploadProcessor(self._plex_with_show(), arr=arr)
        proc.set_options(Options(kometa=True))

        results = proc.process_tv_artwork(_tv_artwork(season=3, episode=None))

        assert results[0].startswith("⚠️")
        assert not capture_kometa_saves

    def test_regression_guard_arr_disabled_still_warns_for_missing_season(self, configured, capture_kometa_saves):
        arr = FakeArr(tv_enabled=False)
        proc = UploadProcessor(self._plex_with_show(), arr=arr)
        proc.set_options(Options(kometa=True))

        results = proc.process_tv_artwork(_tv_artwork(season=2, episode=None))

        assert results[0].startswith("⚠️")
        assert not capture_kometa_saves

    def test_season_present_in_plex_does_not_call_sonarr(self, configured, capture_kometa_saves):
        calls = []
        arr_series = _arr_series(season_numbers={1, 2})

        class TrackingSonarr(FakeSonarr):
            def find_series(self, tmdb_id, title, year):
                calls.append((tmdb_id, title, year))
                return super().find_series(tmdb_id, title, year)

        arr = FakeArr(sonarr=TrackingSonarr(series=arr_series))
        proc = UploadProcessor(self._plex_with_show(), arr=arr)
        proc.set_options(Options(kometa=True))

        results = proc.process_tv_artwork(_tv_artwork(season=1, episode=None))

        assert results[0].startswith("✅")
        assert not calls  # Sonarr should never be consulted when the season is already in Plex
