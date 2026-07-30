"""Tests that a failed upload never strips the label of the artwork it was replacing.

The artwork-ID label is how the uploader recognises artwork it applied itself. If the old label is
removed and the replacement upload then fails, the item is left locked with no label at all, which
every later run reads as artwork the user set by hand and leaves alone forever.
"""

import pytest

from models.options import Options
from plex.plex_uploader import PlexUploader
from utils import utils

ASSETS = "https://theposterdb.com/api/assets"


@pytest.fixture(autouse=True)
def _no_rate_limit_sleep(monkeypatch):
    # upload_to_plex sleeps TPDB_RATE_LIMIT_DELAY after a real upload; skip it in tests.
    monkeypatch.setattr("plex.plex_uploader.time.sleep", lambda *a: None)


def _url(asset_id):
    return f"{ASSETS}/{asset_id}"


def _label(prefix, asset_id):
    return prefix + utils.calculate_md5(_url(asset_id))


class _Field:
    def __init__(self, name, locked):
        self.name = name
        self.locked = locked


class _Target:
    """Minimal stand-in for a plexapi Movie."""

    def __init__(self, labels=(), locked=False, rating_key=1):
        self.labels = list(labels)
        self.fields = [_Field("thumb", locked)]
        self.librarySectionTitle = "Movies"
        self.ratingKey = rating_key
        self.uploaded = []
        self.fail_upload = False

    def uploadPoster(self, url=None, filepath=None):
        if self.fail_upload:
            raise RuntimeError("Plex upload failed")
        self.uploaded.append(url or filepath)

    def addLabel(self, label):
        self.labels.append(str(label))

    def removeLabel(self, label, *args):
        self.labels = [existing for existing in self.labels if str(existing) != str(label)]

    def reload(self):
        pass


def _uploader(target, candidate_id, *, confirm_match=None):
    uploader = PlexUploader(target, "Poster", "PID:")
    uploader.set_options(Options())
    uploader.set_artwork({"id": candidate_id, "url": _url(candidate_id), "source": "theposterdb"})
    uploader.set_description("The Dark Knight")
    uploader.track_artwork_ids = True
    uploader.confirm_match = confirm_match
    return uploader


def test_failed_upload_keeps_the_existing_label():
    # The item carries the label of the poster we applied last time. The replacement upload throws,
    # so the old label must survive: next run has to still recognise the item as ours.
    old = _label("PID:", 666275)
    target = _Target(labels=[old])
    target.fail_upload = True

    result = _uploader(target, 670744).upload_to_plex()

    assert result.startswith("❌")
    assert old in target.labels
    assert target.uploaded == []


def test_successful_upload_swaps_the_label():
    old = _label("PID:", 666275)
    target = _Target(labels=[old])

    result = _uploader(target, 670744).upload_to_plex()

    assert result.startswith("✅")
    assert target.uploaded == [_url(670744)]
    assert old not in target.labels
    assert _label("PID:", 670744) in target.labels


def test_declined_match_keeps_the_existing_label():
    # A local title match that the poster page then contradicts declines the upload. Nothing was
    # replaced, so the old label must stay.
    old = _label("PID:", 666275)
    target = _Target(labels=[old])

    result = _uploader(target, 670744, confirm_match=lambda: False).upload_to_plex()

    assert result.startswith("⚠️")
    assert old in target.labels
    assert target.uploaded == []
