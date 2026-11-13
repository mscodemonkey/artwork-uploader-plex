from types import SimpleNamespace

import pytest

from utils import utils


@pytest.mark.unit
def test_docker_socket_is_unavailable_when_not_mounted(tmp_path, monkeypatch):
    socket_path = tmp_path / "docker.sock"
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(utils, "DOCKER_SOCKET_PATH", str(socket_path))
    monkeypatch.setattr(
        utils.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Docker CLI should not run without a mounted socket"),
    )

    available, reason = utils.is_docker_socket_available()

    assert available is False
    assert "not mounted" in reason


@pytest.mark.unit
@pytest.mark.parametrize(
    ("returncode", "stderr", "expected_available"),
    [(0, "", True), (1, "permission denied", False)],
)
def test_docker_socket_availability_uses_docker_server_response(
    monkeypatch, returncode, stderr, expected_available
):
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    monkeypatch.setattr(
        utils.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=returncode, stderr=stderr),
    )

    available, reason = utils.is_docker_socket_available()

    assert available is expected_available
    if expected_available:
        assert reason == ""
    else:
        assert "permission denied" in reason
