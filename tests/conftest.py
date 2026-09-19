"""Test harness for web_routes.py: a Flask app with the real routes and socket handlers on it.

web_routes.py registers everything through setup_routes and setup_socket_handlers rather than at
import time, so a test builds its own app and drives it with Flask's test client and the
Flask-SocketIO one. Both clients share a session when the socket client is given the HTTP client,
which is what lets an authentication test log in over HTTP and then emit over the socket.
"""

import re
import types
from pathlib import Path

import pytest
from flask import Flask
from flask_socketio import SocketIO

import core.globals as app_globals
import web_routes

REPO_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DEFAULTS = {
    "auth_enabled": False,
    "auth_username": "",
    "auth_password_hash": "",
    "oidc_enabled": False,
    "oidc_label": "OIDC",
    "oidc_issuer": "",
    "oidc_client_id": "",
    "oidc_client_secret": "",
    "oidc_scopes": [],
    "oidc_groups_claim": "",
    "oidc_allowed_groups": [],
    "external_url": "",
    "webhook_token": "",
    "enable_webhooks": False,
}


def make_config(**overrides):
    """A stand-in config carrying the settings the routes and handlers read."""
    settings = dict(CONFIG_DEFAULTS)
    settings.update(overrides)
    return types.SimpleNamespace(**settings)


class WebHarness:
    """The app under test and the two clients that drive it."""

    def __init__(self, app, socket, config):
        self.app = app
        self.socket = socket
        self.config = config

    def http_client(self):
        return self.app.test_client()

    def socket_client(self, http_client=None):
        return self.socket.test_client(self.app, flask_test_client=http_client)


@pytest.fixture
def web_harness(monkeypatch):
    config = make_config()

    app = Flask("web_routes_test", template_folder=str(REPO_ROOT / "templates"))
    app.config["SECRET_KEY"] = "test-secret-key"
    app.config["SERVER_NAME"] = "localhost"

    socket = SocketIO(app, async_mode="threading")

    monkeypatch.setattr(app_globals, "config", config)
    monkeypatch.setattr(app_globals, "web_socket", socket)

    web_routes.setup_routes(app, config)
    web_routes.setup_socket_handlers(config=config, filename_pattern=re.compile(r".*"))

    return WebHarness(app, socket, config)
