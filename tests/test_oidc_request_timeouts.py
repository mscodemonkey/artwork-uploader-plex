"""Every OIDC call to the identity provider carries a timeout.

A provider that accepts the connection and then goes quiet blocks the worker thread forever,
so these assert the timeout reaches the request rather than that the login works.
"""

import pytest

import web_routes
from core.constants import OIDC_REQUEST_TIMEOUT

DISCOVERY = {
    "authorization_endpoint": "https://idp.example/authorize",
    "token_endpoint": "https://idp.example/token",
    "userinfo_endpoint": "https://idp.example/userinfo",
    "end_session_endpoint": "https://idp.example/logout",
}

USER_INFO = {"preferred_username": "boss"}


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _StubOAuthSession:
    """Stands in for OAuth2Session and records the keyword arguments of every call."""

    calls = []

    def __init__(self, **kwargs):
        self.token = {"id_token": "an-id-token"}

    def get(self, url, **kwargs):
        _StubOAuthSession.calls.append((url, kwargs))
        return _Response(USER_INFO if url.endswith("/userinfo") else DISCOVERY)

    def authorization_url(self, endpoint):
        return f"{endpoint}?client_id=test", "a-state"

    def fetch_token(self, **kwargs):
        _StubOAuthSession.calls.append(("fetch_token", kwargs))
        return self.token


@pytest.fixture
def oidc_harness(web_harness, monkeypatch):
    _StubOAuthSession.calls = []
    web_harness.config.oidc_enabled = True
    web_harness.config.oidc_issuer = "https://idp.example"
    web_harness.config.oidc_scopes = ["openid", "profile"]
    web_harness.config.oidc_client_id = "artwork-uploader"
    web_harness.config.oidc_client_secret = "a-secret"
    monkeypatch.setattr(web_routes, "OAuth2Session", _StubOAuthSession)
    return web_harness


@pytest.mark.unit
def test_the_login_discovery_fetch_carries_a_timeout(oidc_harness):
    response = oidc_harness.http_client().post("/login", data={"oidc-login": "1"})

    assert response.status_code == 302
    url, kwargs = _StubOAuthSession.calls[0]
    assert url.endswith("/.well-known/openid-configuration")
    assert kwargs["timeout"] == OIDC_REQUEST_TIMEOUT


@pytest.mark.unit
def test_every_callback_request_carries_a_timeout(oidc_harness):
    client = oidc_harness.http_client()
    with client.session_transaction() as flask_session:
        flask_session["oauth_state"] = "a-state"

    response = client.get("/login/oidc/callback?state=a-state&code=an-auth-code")

    assert response.status_code == 302
    assert [call[0] for call in _StubOAuthSession.calls] == [
        "https://idp.example/.well-known/openid-configuration",
        "fetch_token",
        "https://idp.example/userinfo",
    ]
    for _, kwargs in _StubOAuthSession.calls:
        assert kwargs["timeout"] == OIDC_REQUEST_TIMEOUT


@pytest.mark.unit
def test_the_logout_discovery_fetch_carries_a_timeout(oidc_harness, monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return _Response(DISCOVERY)

    monkeypatch.setattr(web_routes.requests, "get", fake_get)

    client = oidc_harness.http_client()
    with client.session_transaction() as flask_session:
        flask_session["authenticated"] = True
        flask_session["auth_type"] = "oidc"

    client.get("/logout")

    assert seen["url"].endswith("/.well-known/openid-configuration")
    assert seen["kwargs"]["timeout"] == OIDC_REQUEST_TIMEOUT
