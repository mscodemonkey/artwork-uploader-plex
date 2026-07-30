"""Tests for allow_artist_updates: taking an artist's newer poster for artwork the uploader
applied itself, while leaving hand-set customs and other artists' artwork alone."""

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

    def __init__(self, labels=(), locked=True, rating_key=1):
        self.labels = list(labels)
        self.fields = [_Field("thumb", locked)]
        self.librarySectionTitle = "Movies"
        self.ratingKey = rating_key
        self.uploaded = []

    def uploadPoster(self, url=None, filepath=None):
        self.uploaded.append(url or filepath)

    def addLabel(self, label):
        self.labels.append(str(label))

    def removeLabel(self, label, *args):
        self.labels = [existing for existing in self.labels if str(existing) != str(label)]

    def reload(self):
        pass


# djchrisallen owns two Dark Knight posters: an older one (666275) and a newer one (670744).
ARTIST_ASSETS = {
    utils.calculate_md5(_url(666275)): 666275,
    utils.calculate_md5(_url(670744)): 670744,
}


def _uploader(target, candidate_id, *, allow, artist_assets=ARTIST_ASSETS, skip_locked=True):
    uploader = PlexUploader(target, "Poster", "PID:")
    uploader.set_options(Options())
    uploader.set_artwork({"id": candidate_id, "url": _url(candidate_id), "source": "theposterdb"})
    uploader.set_description("The Dark Knight")
    uploader.skip_locked = skip_locked
    uploader.track_artwork_ids = True
    uploader.allow_artist_updates = allow
    uploader.artist_assets = artist_assets
    return uploader


# --- the allow_artist_updates truth table -----------------------------------------------

def test_hand_set_custom_is_never_touched():
    # A locked field with no artwork-uploader label of this type was set by hand. This must hold
    # whether the option is on or off - it is the whole safety property.
    for allow in (False, True):
        target = _Target(labels=[], locked=True)
        result = _uploader(target, 670744, allow=allow).upload_to_plex()
        assert result.startswith("🔒")
        assert target.uploaded == []


def test_a_different_artists_poster_is_not_taken():
    # The current poster is one WE applied, but from another artist (its md5 is not in this
    # artist's asset map). Same-artist-only: leave it alone.
    target = _Target(labels=[_label("PID:", 999999)], locked=True)
    result = _uploader(target, 670744, allow=True).upload_to_plex()
    assert result.startswith("🔒")
    assert target.uploaded == []


def test_a_newer_poster_from_the_same_artist_is_taken():
    target = _Target(labels=[_label("PID:", 666275)], locked=True)
    result = _uploader(target, 670744, allow=True).upload_to_plex()
    assert result.startswith("✅")
    assert target.uploaded == [_url(670744)]


def test_an_older_poster_from_the_same_artist_is_refused():
    # Current is the newer poster; a run offering the older one must not move backwards.
    target = _Target(labels=[_label("PID:", 670744)], locked=True)
    result = _uploader(target, 666275, allow=True).upload_to_plex()
    assert result.startswith("🔒")
    assert target.uploaded == []


def test_the_same_poster_is_left_unchanged():
    target = _Target(labels=[_label("PID:", 670744)], locked=True)
    result = _uploader(target, 670744, allow=True).upload_to_plex()
    assert result.startswith("⏩")
    assert target.uploaded == []


def test_option_off_still_skips_a_locked_item_we_own():
    target = _Target(labels=[_label("PID:", 666275)], locked=True)
    result = _uploader(target, 670744, allow=False).upload_to_plex()
    assert result.startswith("🔒")
    assert target.uploaded == []


def test_a_file_upload_candidate_never_qualifies():
    # A ZIP/file upload has a non-numeric id, so it can't be compared by asset id - protect.
    target = _Target(labels=[_label("PID:", 666275)], locked=True)
    uploader = _uploader(target, 670744, allow=True)
    uploader.set_artwork({"id": "Upload", "checksum": "abc", "source": "upload"})
    result = uploader.upload_to_plex()
    assert result.startswith("🔒")
    assert target.uploaded == []
