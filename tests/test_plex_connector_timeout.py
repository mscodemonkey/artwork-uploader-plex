"""Tests that PlexConnector.connect() uses the configurable connect timeout, and falls back to
today's hardcoded default when no config has been loaded yet.
"""

from core import globals
from plex.plex_connector import PlexConnector


class _FakePlexServer:
    """Stands in for plexapi.server.PlexServer, recording the timeout it was constructed with."""

    last_timeout = None

    def __init__(self, base_url, token, timeout=None):
        _FakePlexServer.last_timeout = timeout


def test_connect_uses_the_configured_timeout(monkeypatch):
    monkeypatch.setattr("plex.plex_connector.PlexServer", _FakePlexServer)

    class _FakeConfig:
        plex_connect_timeout = 42

    monkeypatch.setattr(globals, "config", _FakeConfig())

    connector = PlexConnector("http://plex.example:32400", "token")
    connector.connect()

    assert _FakePlexServer.last_timeout == 42


def test_connect_falls_back_to_the_default_timeout_when_config_is_unset(monkeypatch):
    monkeypatch.setattr("plex.plex_connector.PlexServer", _FakePlexServer)
    monkeypatch.setattr(globals, "config", None)

    connector = PlexConnector("http://plex.example:32400", "token")
    connector.connect()

    assert _FakePlexServer.last_timeout == 10
