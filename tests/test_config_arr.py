import json

import pytest

from core.config import Config

pytestmark = pytest.mark.unit


@pytest.fixture
def config(tmp_path):
    cfg = Config(config_path=str(tmp_path / "config.json"))
    cfg.load()
    return cfg


class TestResolveArrLibrary:

    def test_no_map_falls_back_to_first_movie_library(self, config):
        config.movie_library = ["Movies", "4K Movies"]
        assert config.resolve_arr_library("/data/media/movies/Foo", "movie") == "Movies"

    def test_no_map_falls_back_to_first_tv_library(self, config):
        config.tv_library = ["TV Shows", "Anime"]
        assert config.resolve_arr_library("/data/media/tv/Foo", "tv") == "TV Shows"

    def test_legacy_string_library_config_fallback(self, config):
        config.movie_library = "Movies"
        assert config.resolve_arr_library("/data/media/movies/Foo", "movie") == "Movies"

    def test_none_root_path_uses_fallback(self, config):
        config.movie_library = ["Movies"]
        assert config.resolve_arr_library(None, "movie") == "Movies"

    def test_exact_and_prefix_match(self, config):
        config.arr_root_folder_library_map = {"/data/media/movies": "Movies"}
        assert config.resolve_arr_library("/data/media/movies", "movie") == "Movies"
        assert config.resolve_arr_library("/data/media/movies/Foo (2020)", "movie") == "Movies"

    def test_longest_prefix_wins(self, config):
        config.arr_root_folder_library_map = {
            "/data/media/movies": "Movies",
            "/data/media/movies/kids": "Kids Movies",
        }
        assert config.resolve_arr_library("/data/media/movies/kids/Foo", "movie") == "Kids Movies"
        assert config.resolve_arr_library("/data/media/movies/Foo", "movie") == "Movies"

    def test_trailing_slash_insensitive(self, config):
        config.arr_root_folder_library_map = {"/data/media/movies/": "Movies"}
        assert config.resolve_arr_library("/data/media/movies", "movie") == "Movies"
        assert config.resolve_arr_library("/data/media/movies/Foo", "movie") == "Movies"

    def test_similar_but_unrelated_prefix_does_not_match(self, config):
        # "/data/media/movies-4k" should not match the "/data/media/movies" mapping
        config.arr_root_folder_library_map = {"/data/media/movies": "Movies"}
        config.movie_library = ["Fallback"]
        assert config.resolve_arr_library("/data/media/movies-4k/Foo", "movie") == "Fallback"

    def test_unmapped_path_uses_fallback(self, config):
        config.arr_root_folder_library_map = {"/data/media/movies": "Movies"}
        config.tv_library = ["TV Shows"]
        assert config.resolve_arr_library("/unmapped/path", "tv") == "TV Shows"

    def test_empty_fallback_list_returns_empty_string(self, config):
        config.movie_library = []
        assert config.resolve_arr_library(None, "movie") == ""


class TestConfigRoundTrip:

    def test_new_keys_persist_through_save_and_load(self, config):
        config.radarr_url = "http://localhost:7878"
        config.radarr_api_key = "radarr-key"
        config.sonarr_url = "http://localhost:8989"
        config.sonarr_api_key = "sonarr-key"
        config.arr_root_folder_library_map = {"/data/media/movies": "Movies"}
        config.preseed_arr = True
        config.save()

        reloaded = Config(config_path=config.path)
        reloaded.load()

        assert reloaded.radarr_url == "http://localhost:7878"
        assert reloaded.radarr_api_key == "radarr-key"
        assert reloaded.sonarr_url == "http://localhost:8989"
        assert reloaded.sonarr_api_key == "sonarr-key"
        assert reloaded.arr_root_folder_library_map == {"/data/media/movies": "Movies"}
        assert reloaded.preseed_arr is True

    def test_missing_keys_in_existing_config_file_default_safely(self, tmp_path):
        # Simulates an upgrade from a config.json written before this feature existed.
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"base_url": "http://plex", "token": "abc"}))

        cfg = Config(config_path=str(config_path))
        cfg.load()

        assert cfg.preseed_arr is False
        assert cfg.radarr_url == ""
        assert cfg.arr_root_folder_library_map == {}
        # stage_specials should default to True for configs missing the key
        assert cfg.stage_specials is True

    def test_new_config_defaults(self, config):
        assert config.preseed_arr is False
        assert config.stage_specials is True
