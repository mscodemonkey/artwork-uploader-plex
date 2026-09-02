"""Unit test for the load_run_history Socket.IO handler (web_routes.py)."""

import re
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import core.globals as globals
import web_routes
from services.run_history import RunHistory
from core.enums import RunType, RunTrigger, RunOutcome

OUTCOME_SUCCESS = RunOutcome.SUCCESS.value
RUN_TYPE_BULK = RunType.BULK.value
RUN_TYPE_WEBHOOK = RunType.WEBHOOK.value
TRIGGER_MANUAL = RunTrigger.MANUAL.value
TRIGGER_RADARR = RunTrigger.RADARR.value


def _iso():
    return datetime.now(timezone.utc).isoformat()


class _StubSocket:
    """Records handlers registered via @socket.on(event) instead of a real Socket.IO server."""

    def __init__(self):
        self.handlers = {}

    def on(self, event):
        def register(func):
            self.handlers[event] = func
            return func
        return register


@pytest.fixture
def stub_socket(monkeypatch):
    socket = _StubSocket()
    monkeypatch.setattr(globals, "web_socket", socket)
    web_routes.setup_socket_handlers(config=None, filename_pattern=re.compile(r".*"))
    return socket


@pytest.mark.unit
def test_load_run_history_emits_recent_runs(tmp_path, stub_socket, monkeypatch):
    history = RunHistory(str(tmp_path / "run_history.json"))
    history.add_run(RUN_TYPE_BULK, "bulk_import.txt", _iso(), _iso(), TRIGGER_MANUAL, OUTCOME_SUCCESS)
    monkeypatch.setattr(web_routes, "RunHistory", lambda: history)

    emitted = {}

    def fake_notify_web(instance, event, data_to_include=None, silent=False):
        emitted["event"] = event
        emitted["data"] = data_to_include

    with patch("web_routes.notify_web", side_effect=fake_notify_web):
        stub_socket.handlers["load_run_history"]({"instance_id": "abc"})

    assert emitted["event"] == "load_run_history"
    assert len(emitted["data"]["runs"]) == 1
    assert emitted["data"]["runs"][0]["label"] == "bulk_import.txt"
    assert emitted["data"]["run_type"] == "all"


@pytest.mark.unit
def test_load_run_history_narrows_to_the_requested_run_type(tmp_path, stub_socket, monkeypatch):
    history = RunHistory(str(tmp_path / "run_history.json"))
    history.add_run(RUN_TYPE_BULK, "bulk_import.txt", _iso(), _iso(), TRIGGER_MANUAL, OUTCOME_SUCCESS)
    history.add_run(RUN_TYPE_WEBHOOK, "The Matrix (1999)", _iso(), _iso(), TRIGGER_RADARR, OUTCOME_SUCCESS)
    monkeypatch.setattr(web_routes, "RunHistory", lambda: history)

    emitted = {}

    def fake_notify_web(instance, event, data_to_include=None, silent=False):
        emitted["data"] = data_to_include

    with patch("web_routes.notify_web", side_effect=fake_notify_web):
        stub_socket.handlers["load_run_history"]({"instance_id": "abc", "run_type": RUN_TYPE_WEBHOOK})

    assert [run["label"] for run in emitted["data"]["runs"]] == ["The Matrix (1999)"]
    assert emitted["data"]["run_type"] == RUN_TYPE_WEBHOOK


@pytest.mark.unit
def test_an_unknown_run_type_falls_back_to_every_run(tmp_path, stub_socket, monkeypatch):
    """The filter comes off the wire, so a value that isn't a run type must not silently
    return nothing - it shows everything, the way the unfiltered table does."""
    history = RunHistory(str(tmp_path / "run_history.json"))
    history.add_run(RUN_TYPE_BULK, "bulk_import.txt", _iso(), _iso(), TRIGGER_MANUAL, OUTCOME_SUCCESS)
    monkeypatch.setattr(web_routes, "RunHistory", lambda: history)

    emitted = {}

    def fake_notify_web(instance, event, data_to_include=None, silent=False):
        emitted["data"] = data_to_include

    with patch("web_routes.notify_web", side_effect=fake_notify_web):
        stub_socket.handlers["load_run_history"]({"instance_id": "abc", "run_type": "nonsense"})

    assert len(emitted["data"]["runs"]) == 1
    assert emitted["data"]["run_type"] == "all"


@pytest.mark.unit
def test_load_run_history_with_no_runs_emits_an_empty_list(tmp_path, stub_socket, monkeypatch):
    history = RunHistory(str(tmp_path / "run_history.json"))
    monkeypatch.setattr(web_routes, "RunHistory", lambda: history)

    emitted = {}

    def fake_notify_web(instance, event, data_to_include=None, silent=False):
        emitted["data"] = data_to_include

    with patch("web_routes.notify_web", side_effect=fake_notify_web):
        stub_socket.handlers["load_run_history"]({"instance_id": "abc"})

    assert emitted["data"]["runs"] == []
