"""/api/browse lists directories, so it must not answer before login."""

import pytest


@pytest.mark.unit
def test_browse_redirects_to_login_when_basic_auth_is_on(web_harness):
    web_harness.config.auth_enabled = True

    response = web_harness.http_client().get("/api/browse?path=/")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


@pytest.mark.unit
def test_browse_redirects_to_login_when_oidc_is_on(web_harness):
    web_harness.config.oidc_enabled = True

    response = web_harness.http_client().get("/api/browse?path=/")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


@pytest.mark.unit
def test_browse_answers_a_logged_in_session(web_harness, tmp_path):
    web_harness.config.auth_enabled = True
    (tmp_path / "assets").mkdir()

    client = web_harness.http_client()
    with client.session_transaction() as flask_session:
        flask_session["authenticated"] = True

    response = client.get(f"/api/browse?path={tmp_path}")

    assert response.status_code == 200
    assert [folder["name"] for folder in response.get_json()["folders"]] == ["assets"]


@pytest.mark.unit
def test_browse_stays_open_when_no_authentication_is_configured(web_harness, tmp_path):
    """Auth off is the default, and the settings screen has to reach the picker."""
    (tmp_path / "assets").mkdir()

    response = web_harness.http_client().get(f"/api/browse?path={tmp_path}")

    assert response.status_code == 200
