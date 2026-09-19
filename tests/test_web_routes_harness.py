"""Proves the web_routes.py harness drives both an HTTP route and a socket handler."""

import pytest


@pytest.mark.unit
def test_auth_status_route_reports_the_configured_methods(web_harness):
    web_harness.config.auth_enabled = True
    web_harness.config.oidc_label = "Authentik"

    response = web_harness.http_client().get("/api/auth/status")

    assert response.status_code == 200
    assert response.get_json()["basic_enabled"] is True
    assert response.get_json()["oidc_label"] == "Authentik"


@pytest.mark.unit
def test_a_socket_handler_answers_the_socket_test_client(web_harness):
    client = web_harness.socket_client()

    client.emit("get_auth_status", {"instance_id": "abc"})

    replies = [message for message in client.get_received() if message["name"] == "get_auth_status"]
    assert replies, "get_auth_status sent nothing back"
    assert replies[0]["args"][0]["auth_enabled"] is False


@pytest.mark.unit
def test_the_socket_client_shares_a_session_with_the_http_client(web_harness):
    http_client = web_harness.http_client()
    with http_client.session_transaction() as flask_session:
        flask_session["username"] = "boss"

    client = web_harness.socket_client(http_client)
    client.emit("get_auth_status", {"instance_id": "abc"})

    replies = [message for message in client.get_received() if message["name"] == "get_auth_status"]
    assert replies[0]["args"][0]["username"] == "boss"
