"""The socket does the real work of the web UI, so it must refuse a session that has not logged in.

The gate sits on connect rather than on each handler, so these tests assert on the connection
rather than on any one event. That is what makes the cover hold for handlers added later.
"""

import pytest


@pytest.mark.unit
def test_a_socket_connects_when_no_authentication_is_configured(web_harness):
    assert web_harness.socket_client().is_connected()


@pytest.mark.unit
def test_a_socket_is_refused_when_basic_auth_is_on_and_nobody_has_logged_in(web_harness):
    web_harness.config.auth_enabled = True

    assert not web_harness.socket_client().is_connected()


@pytest.mark.unit
def test_a_socket_is_refused_when_oidc_is_on_and_nobody_has_logged_in(web_harness):
    web_harness.config.oidc_enabled = True

    assert not web_harness.socket_client().is_connected()


@pytest.mark.unit
def test_a_logged_in_session_connects(web_harness):
    web_harness.config.auth_enabled = True

    http_client = web_harness.http_client()
    with http_client.session_transaction() as flask_session:
        flask_session["authenticated"] = True

    assert web_harness.socket_client(http_client).is_connected()


@pytest.mark.unit
def test_a_refused_socket_reaches_no_handler(web_harness):
    """load_config sends the whole config object back, tokens and password hash included."""
    web_harness.config.auth_enabled = True
    client = web_harness.socket_client()

    with pytest.raises(RuntimeError):
        client.emit("load_config", {"instance_id": "abc"})
