"""Saving config.json must not be able to destroy it (core/config.py).

config.json holds the Plex token, the webhook token, the OIDC client secret, the basic
auth password hash and every schedule. It used to be written over the top of the live
file, so a process stopped part way through a save left it truncated and the next load
could not parse it, and all of that had to be entered again by hand. It is now written
to a temporary file alongside it and moved into place, the same shape as the run history
and the Kometa asset writer use.
"""

import json
import os
from unittest.mock import patch

import pytest

from core import config as config_module
from core.config import Config
from core.constants import (
    DOCKER_KOMETA_ASSETS_PATH,
    DOCKER_KOMETA_CONFIG_PATH,
    DOCKER_KOMETA_TEMP_PATH,
)
from core.exceptions import ConfigSaveError, ConfigCreationError


@pytest.fixture
def config(tmp_path):
    config = Config(str(tmp_path / "config.json"))
    config.load()
    return config


@pytest.mark.unit
def test_save_writes_the_configuration(config):
    config.token = "a-plex-token"
    config.oidc_client_secret = "an-oidc-secret"
    config.save()

    with open(config.path, encoding="utf-8") as saved:
        saved_config = json.load(saved)

    assert saved_config["token"] == "a-plex-token"
    assert saved_config["oidc_client_secret"] == "an-oidc-secret"


@pytest.mark.unit
def test_saving_leaves_no_temporary_file_behind(config):
    config.save()

    assert os.path.isfile(config.path)
    assert not os.path.exists(f"{config.path}.tmp")


@pytest.mark.unit
def test_save_keeps_the_permissions_the_file_already_had(config):
    """An administrator who restricted config.json to its owner keeps that after a save."""
    config.save()
    os.chmod(config.path, 0o600)

    config.token = "a-plex-token"
    config.save()

    assert os.stat(config.path).st_mode & 0o777 == 0o600


@pytest.mark.unit
def test_a_failed_save_leaves_the_existing_configuration_intact(config):
    """A write that dies part way cannot take the credentials already on disk with it."""
    config.token = "a-plex-token"
    config.auth_password_hash = "a-password-hash"
    config.save()

    with patch("core.config.json.dump", side_effect=OSError("no space left on device")):
        with pytest.raises(ConfigSaveError):
            config.token = "a-newer-token"
            config.save()

    reloaded = Config(config.path)
    reloaded.load()

    assert reloaded.token == "a-plex-token"
    assert reloaded.auth_password_hash == "a-password-hash"
    assert not os.path.exists(f"{config.path}.tmp")


@pytest.mark.unit
def test_the_first_load_creates_a_readable_file(tmp_path):
    """The default config is written the same way, with nothing there to replace."""
    config = Config(str(tmp_path / "config.json"))
    config.load()

    with open(config.path, encoding="utf-8") as created:
        json.load(created)

    assert not os.path.exists(f"{config.path}.tmp")


@pytest.mark.unit
def test_a_failed_creation_leaves_no_temporary_file_behind(tmp_path):
    """The first load creates the file, and that write goes the same way."""
    config = Config(str(tmp_path / "config.json"))

    with patch("core.config.json.dump", side_effect=OSError("no space left on device")):
        with pytest.raises(ConfigCreationError):
            config.create()

    assert not os.path.exists(config.path)
    assert not os.path.exists(f"{config.path}.tmp")


@pytest.mark.unit
def test_docker_without_kometa_config_mount_disables_and_persists_auto_run(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    saved_paths = {
        "kometa_base": "/host/artwork",
        "temp_dir": "/host/temp",
        "kometa_config_path": "/host/kometa",
    }
    with open(config_path, "w", encoding="utf-8") as config_file:
        json.dump({**saved_paths, "kometa_auto_run": True}, config_file)

    monkeypatch.setattr(config_module.globals, "docker", True)
    monkeypatch.setattr(config_module, "get_host_path", lambda _: "(not defined)")
    monkeypatch.setattr(config_module, "is_docker_socket_available", lambda: (True, ""))

    config = Config(str(config_path))
    config.load()

    with open(config_path, encoding="utf-8") as saved:
        saved_config = json.load(saved)

    assert config.kometa_auto_run is False
    assert saved_config["kometa_auto_run"] is False
    assert {key: saved_config[key] for key in saved_paths} == saved_paths


@pytest.mark.unit
def test_docker_without_kometa_assets_mount_disables_and_persists_save_to_kometa(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    saved_paths = {
        "kometa_base": "/host/artwork",
        "temp_dir": "/host/temp",
        "kometa_config_path": "/host/kometa",
    }
    with open(config_path, "w", encoding="utf-8") as config_file:
        json.dump({**saved_paths, "save_to_kometa": True, "kometa_auto_run": True}, config_file)

    docker_paths = {
        DOCKER_KOMETA_ASSETS_PATH: "(not defined)",
        DOCKER_KOMETA_TEMP_PATH: "/container/temp",
        DOCKER_KOMETA_CONFIG_PATH: "/container/kometa",
    }
    monkeypatch.setattr(config_module.globals, "docker", True)
    monkeypatch.setattr(config_module, "get_host_path", docker_paths.__getitem__)
    monkeypatch.setattr(config_module, "is_docker_socket_available", lambda: (True, ""))

    config = Config(str(config_path))
    config.load()

    with open(config_path, encoding="utf-8") as saved:
        saved_config = json.load(saved)

    assert config.save_to_kometa is False
    assert saved_config["save_to_kometa"] is False
    assert config.kometa_auto_run is True
    assert saved_config["kometa_auto_run"] is True
    assert {key: saved_config[key] for key in saved_paths} == saved_paths


@pytest.mark.unit
def test_docker_without_socket_disables_and_persists_auto_run(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    saved_paths = {
        "kometa_base": "/host/artwork",
        "temp_dir": "/host/temp",
        "kometa_config_path": "/host/kometa",
    }
    with open(config_path, "w", encoding="utf-8") as config_file:
        json.dump({**saved_paths, "kometa_auto_run": True}, config_file)

    docker_paths = {
        DOCKER_KOMETA_ASSETS_PATH: "/container/assets",
        DOCKER_KOMETA_TEMP_PATH: "/container/temp",
        DOCKER_KOMETA_CONFIG_PATH: "/container/kometa",
    }
    monkeypatch.setattr(config_module.globals, "docker", True)
    monkeypatch.setattr(config_module, "get_host_path", docker_paths.__getitem__)
    monkeypatch.setattr(config_module, "is_docker_socket_available", lambda: (False, "socket unavailable"))

    config = Config(str(config_path))
    config.load()

    with open(config_path, encoding="utf-8") as saved:
        saved_config = json.load(saved)

    assert config.kometa_auto_run is False
    assert saved_config["kometa_auto_run"] is False
    assert {key: saved_config[key] for key in saved_paths} == saved_paths


@pytest.mark.unit
def test_non_docker_load_keeps_auto_run_enabled(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    with open(config_path, "w", encoding="utf-8") as config_file:
        json.dump({"kometa_auto_run": True}, config_file)

    monkeypatch.setattr(config_module.globals, "docker", False)
    monkeypatch.setattr(config_module, "is_docker_socket_available", lambda: (False, "socket unavailable"))

    config = Config(str(config_path))
    config.load()

    with open(config_path, encoding="utf-8") as saved:
        saved_config = json.load(saved)

    assert config.kometa_auto_run is True
    assert saved_config["kometa_auto_run"] is True


@pytest.mark.unit
def test_docker_save_preserves_local_kometa_paths(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    saved_paths = {
        "kometa_base": "/host/artwork",
        "temp_dir": "/host/temp",
        "kometa_config_path": "/host/kometa",
    }
    with open(config_path, "w", encoding="utf-8") as config_file:
        json.dump({**saved_paths, "kometa_auto_run": True}, config_file)

    docker_paths = {
        DOCKER_KOMETA_ASSETS_PATH: "/container/assets",
        DOCKER_KOMETA_TEMP_PATH: "/container/temp",
        DOCKER_KOMETA_CONFIG_PATH: "/container/kometa",
    }
    monkeypatch.setattr(config_module.globals, "docker", True)
    monkeypatch.setattr(config_module, "get_host_path", docker_paths.__getitem__)
    monkeypatch.setattr(config_module, "is_docker_socket_available", lambda: (True, ""))

    config = Config(str(config_path))
    config.load()
    config.token = "updated-token"
    config.save()

    with open(config_path, encoding="utf-8") as saved:
        saved_config = json.load(saved)

    assert saved_config["token"] == "updated-token"
    assert {key: saved_config[key] for key in saved_paths} == saved_paths
