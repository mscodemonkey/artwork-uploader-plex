"""allow_artist_updates has to be off whenever track_artwork_ids is off.

The uploader skips a locked field unless allow_artist_updates and candidate_supersedes_current()
both hold, and candidate_supersedes_current() reads the artwork ID labels on the Plex item. With
track_artwork_ids off nothing writes fresh labels, but labels from an earlier tracked run stay on
the item, so a locked field could be replaced on stale information. Resolving the option at
set_options time keeps that out of the uploader entirely."""

import pytest

from core import globals
from models.options import Options
from processors.upload_processor import UploadProcessor


class _Config:
    def __init__(self, track_artwork_ids, allow_artist_updates=False):
        self.track_artwork_ids = track_artwork_ids
        self.allow_artist_updates = allow_artist_updates
        self.save_to_kometa = False
        self.skip_locked_artwork = True


@pytest.fixture
def processor():
    # UploadProcessor.__init__ connects to Plex and loads config.json from disk; set_options is
    # the only thing under test, so build the instance without running it.
    return UploadProcessor.__new__(UploadProcessor)


def _set_options(processor, monkeypatch, *, config, option_on=False):
    monkeypatch.setattr(globals, "config", config)
    processor.config = config
    options = Options()
    options.allow_artist_updates = option_on
    processor.set_options(options)


@pytest.mark.parametrize("option_on, config_on", [(True, False), (False, True), (True, True)])
def test_artist_updates_are_off_without_artwork_id_tracking(processor, monkeypatch, option_on, config_on):
    # However the option is asked for, per scrape or globally, tracking has the final say.
    _set_options(processor, monkeypatch,
                 config=_Config(track_artwork_ids=False, allow_artist_updates=config_on),
                 option_on=option_on)
    assert processor.allow_artist_updates is False


@pytest.mark.parametrize("option_on, config_on", [(True, False), (False, True), (True, True)])
def test_artist_updates_stay_on_with_tracking(processor, monkeypatch, option_on, config_on):
    _set_options(processor, monkeypatch,
                 config=_Config(track_artwork_ids=True, allow_artist_updates=config_on),
                 option_on=option_on)
    assert processor.allow_artist_updates is True


def test_artist_updates_stay_off_when_nobody_asked(processor, monkeypatch):
    _set_options(processor, monkeypatch,
                 config=_Config(track_artwork_ids=True, allow_artist_updates=False),
                 option_on=False)
    assert processor.allow_artist_updates is False


def test_the_debug_message_still_fires_when_the_option_is_dropped(processor, monkeypatch):
    # The message explains why the option did nothing, so it has to survive the option being
    # resolved to False before the check.
    messages = []
    monkeypatch.setattr("processors.upload_processor.debug_me",
                        lambda message, *args, **kwargs: messages.append(message))
    _set_options(processor, monkeypatch,
                 config=_Config(track_artwork_ids=False, allow_artist_updates=True))
    assert any("track_artwork_ids is off" in message for message in messages)
