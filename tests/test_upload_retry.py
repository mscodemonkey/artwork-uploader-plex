"""Tests for retrying a transient upload failure with backoff.

A timeout, a dropped connection, or a 5xx from Plex is worth trying again - that's the exact
failure upstream issue #51 reported ("Uploading gives Read timed out error, but still works,
albeit very slowly"). A 401 or a 404 never is, so it must fail on the first attempt rather than
burn the retry budget. An item that eventually succeeds must read back as a normal success, not as
an error - only one that exhausts its retries counts as an error, and it must say how many
attempts it had.
"""

import pytest
import requests
import plexapi.exceptions

from core.config import Config
from core.retry import is_transient_error, call_with_retry
from models.options import Options
from plex.plex_uploader import PlexUploader
from utils import utils


def test_config_defaults_match_todays_hardcoded_timeouts(tmp_path):
    # Nothing changes for anyone who doesn't touch these settings: the defaults must match the
    # values that were hardcoded before they became configurable.
    config = Config(config_path=str(tmp_path / "config.json"))
    assert config.plex_connect_timeout == 10
    assert config.plex_test_connection_timeout == 5
    assert config.kometa_download_timeout == 5
    assert config.upload_retry_attempts == 3
    assert config.upload_retry_backoff_seconds == 1


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Retries wait between attempts; skip the wait so the tests run instantly.
    monkeypatch.setattr("core.retry.time.sleep", lambda *a: None)
    monkeypatch.setattr("plex.plex_uploader.time.sleep", lambda *a: None)


# ---------------------- is_transient_error ----------------------

def test_timeout_and_connection_error_are_transient():
    assert is_transient_error(requests.exceptions.Timeout())
    assert is_transient_error(requests.exceptions.ConnectionError())


def test_5xx_http_error_is_transient():
    response = requests.Response()
    response.status_code = 503
    assert is_transient_error(requests.exceptions.HTTPError(response=response))


def test_401_and_404_are_not_transient():
    response_401 = requests.Response()
    response_401.status_code = 401
    response_404 = requests.Response()
    response_404.status_code = 404
    assert not is_transient_error(requests.exceptions.HTTPError(response=response_401))
    assert not is_transient_error(requests.exceptions.HTTPError(response=response_404))
    assert not is_transient_error(plexapi.exceptions.Unauthorized("(401) Unauthorized; ..."))
    assert not is_transient_error(plexapi.exceptions.BadRequest("(404) Not Found; ..."))


def test_http_error_without_a_response_is_not_transient():
    # raise_for_status() always attaches a response, but is_transient_error() must not crash if
    # something else raises an HTTPError bare.
    assert not is_transient_error(requests.exceptions.HTTPError("no response attached"))


def test_5xx_plexapi_bad_request_is_transient():
    assert is_transient_error(plexapi.exceptions.BadRequest("(500) Internal Server Error; ..."))


def test_unrelated_error_is_not_transient():
    assert not is_transient_error(RuntimeError("boom"))


# ---------------------- call_with_retry ----------------------

def test_succeeds_first_try_without_retrying():
    result, attempts = call_with_retry(lambda: "ok", attempts=3, backoff=1)
    assert result == "ok"
    assert attempts == 1


def test_retries_a_transient_failure_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.exceptions.Timeout("slow")
        return "ok"

    result, attempts = call_with_retry(flaky, attempts=3, backoff=1)
    assert result == "ok"
    assert attempts == 3


def test_does_not_retry_a_non_transient_failure():
    calls = {"n": 0}

    def unauthorized():
        calls["n"] += 1
        raise plexapi.exceptions.Unauthorized("(401) Unauthorized; ...")

    with pytest.raises(plexapi.exceptions.Unauthorized) as excinfo:
        call_with_retry(unauthorized, attempts=3, backoff=1)
    assert calls["n"] == 1
    assert excinfo.value.attempts == 1


def test_raises_after_exhausting_attempts():
    calls = {"n": 0}

    def always_times_out():
        calls["n"] += 1
        raise requests.exceptions.Timeout("slow")

    with pytest.raises(requests.exceptions.Timeout) as excinfo:
        call_with_retry(always_times_out, attempts=3, backoff=1)
    assert calls["n"] == 3
    assert excinfo.value.attempts == 3


# ---------------------- PlexUploader.upload_to_plex integration ----------------------

ASSETS = "https://theposterdb.com/api/assets"


def _url(asset_id):
    return f"{ASSETS}/{asset_id}"


def _label(prefix, asset_id):
    return prefix + utils.calculate_md5(_url(asset_id))


class _Field:
    def __init__(self, name, locked):
        self.name = name
        self.locked = locked


class _Target:
    """Minimal stand-in for a plexapi Movie whose uploadPoster fails a set number of times
       before succeeding, or fails every time."""

    def __init__(self, labels=(), fail_times=0, fail_exception=None):
        self.labels = list(labels)
        self.fields = [_Field("thumb", False)]
        self.librarySectionTitle = "Movies"
        self.uploaded = []
        self.fail_times = fail_times
        self.fail_exception = fail_exception or requests.exceptions.Timeout("slow")
        self.calls = 0

    def uploadPoster(self, url=None, filepath=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.fail_exception
        self.uploaded.append(url or filepath)

    def addLabel(self, label):
        self.labels.append(str(label))

    def removeLabel(self, label, *args):
        self.labels = [existing for existing in self.labels if str(existing) != str(label)]

    def reload(self):
        pass


def _uploader(target, candidate_id, retry_attempts=3):
    uploader = PlexUploader(target, "Poster", "PID:")
    uploader.set_options(Options())
    uploader.set_artwork({"id": candidate_id, "url": _url(candidate_id), "source": "theposterdb"})
    uploader.set_description("The Dark Knight")
    uploader.track_artwork_ids = True
    uploader.retry_attempts = retry_attempts
    uploader.retry_backoff = 1
    return uploader


def test_transient_failure_that_recovers_is_not_reported_as_an_error():
    target = _Target(fail_times=2)  # fails twice, succeeds on the third attempt

    result = _uploader(target, 670744).upload_to_plex()

    assert result.startswith("✅")
    assert target.calls == 3
    assert target.uploaded == [_url(670744)]


def test_exhausted_retries_are_reported_as_an_error_with_attempt_count():
    target = _Target(fail_times=99)  # never succeeds

    result = _uploader(target, 670744, retry_attempts=3).upload_to_plex()

    assert result.startswith("❌")
    assert target.calls == 3
    assert "after 3 attempt(s)" in result


def test_non_transient_failure_is_not_retried():
    target = _Target(fail_times=99, fail_exception=RuntimeError("Plex upload failed"))

    result = _uploader(target, 670744, retry_attempts=3).upload_to_plex()

    assert result.startswith("❌")
    assert target.calls == 1
    assert "attempt(s)" not in result
