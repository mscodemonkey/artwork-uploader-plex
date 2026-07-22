"""Unit tests for the Sonarr/Radarr import webhook (services/webhook_service.py)."""

from unittest.mock import MagicMock

import pytest

from core.constants import ARTWORK_ID_MAP, ARTWORK_TYPE_MAP
from plex.plex_uploader import PlexUploader
from services.asset_index import AssetIndex
from services.webhook_service import WebhookEvent, WebhookService, parse_event

FAR_FUTURE = "2999-01-01T00:00:00+00:00"


@pytest.fixture
def index(tmp_path):
    return AssetIndex(str(tmp_path / "asset_index.db"))


def _rec(index, user, asset_id, title, year, media_type, season=None):
    index.record(user, [{
        "id": asset_id, "title": title, "year": year, "season": season,
        "media_type": media_type, "author": user,
        "url": f"https://theposterdb.com/api/assets/{asset_id}",
    }])


# ------------------------------- parse_event -------------------------------

@pytest.mark.unit
def test_parse_radarr_download():
    event = parse_event({"eventType": "Download",
                         "movie": {"title": "Dune", "year": 2021, "tmdbId": 438631}})
    assert isinstance(event, WebhookEvent)
    assert (event.kind, event.title, event.year, event.tmdb_id, event.source) == \
           ("movie", "Dune", 2021, 438631, "radarr")
    assert event.seasons == frozenset()


@pytest.mark.unit
def test_parse_sonarr_download_multi_episode():
    event = parse_event({"eventType": "Download",
                         "series": {"title": "Severance", "year": 2022, "tvdbId": 371980, "tmdbId": 95396},
                         "episodes": [{"seasonNumber": 1}, {"seasonNumber": 2}, {"seasonNumber": 0}]})
    assert event.kind == "tv"
    assert event.tvdb_id == 371980 and event.tmdb_id == 95396
    assert event.seasons == frozenset({0, 1, 2})   # season 0 (Specials) is kept


@pytest.mark.unit
def test_parse_csharp_zero_defaults_are_none():
    event = parse_event({"eventType": "Download",
                         "movie": {"title": "Nope", "year": 0, "tmdbId": 0}})
    assert event.year is None and event.tmdb_id is None


@pytest.mark.unit
def test_parse_test_and_ignored_events():
    assert parse_event({"eventType": "Test"}) == "test"
    for event_type in ("Grab", "MovieAdded", "Rename", "Health", "SeriesAdd"):
        assert parse_event({"eventType": event_type, "movie": {"title": "X"}}) is None
    assert parse_event({}) is None                                   # missing eventType
    assert parse_event({"eventType": "Download"}) is None            # no movie/series
    assert parse_event({"eventType": "Download", "movie": {}}) is None  # no title
    assert parse_event("not a dict") is None                         # never raises


# --------------------------------- lookup ----------------------------------

@pytest.mark.unit
def test_lookup_preferred_user_wins(index):
    _rec(index, "filler", 999, "Heat", 1995, "movie_poster")   # newer id, less preferred
    _rec(index, "preferred", 1, "Heat", 1995, "movie_poster")
    row = index.lookup(["preferred", "filler"], "Heat", 1995, ["movie_poster"])
    assert row["user_key"] == "preferred"


@pytest.mark.unit
def test_lookup_newest_within_user(index):
    _rec(index, "user", 1, "Heat", 1995, "movie_poster")
    _rec(index, "user", 5, "Heat", 1995, "movie_poster")
    assert index.lookup(["user"], "Heat", 1995, ["movie_poster"])["asset_id"] == 5


@pytest.mark.unit
def test_lookup_year_exact_then_nearby(index):
    _rec(index, "user", 1, "Heat", 1995, "movie_poster")
    assert index.lookup(["user"], "Heat", 1995, ["movie_poster"]) is not None
    assert index.lookup(["user"], "Heat", 1996, ["movie_poster"]) is not None   # +/-1
    assert index.lookup(["user"], "Heat", 2010, ["movie_poster"]) is None       # too far


@pytest.mark.unit
def test_lookup_year_none_ambiguity(index):
    _rec(index, "user", 1, "Solo Title", 2020, "movie_poster")
    assert index.lookup(["user"], "Solo Title", None, ["movie_poster"]) is not None
    _rec(index, "user", 2, "Solo Title", 1990, "movie_poster")   # now two distinct years
    assert index.lookup(["user"], "Solo Title", None, ["movie_poster"]) is None


@pytest.mark.unit
def test_lookup_season_and_show_cover(index):
    _rec(index, "user", 10, "Severance", 2022, "show_cover")
    _rec(index, "user", 11, "Severance", 2022, "season_cover", season=0)
    _rec(index, "user", 12, "Severance", 2022, "season_cover", season=1)
    assert index.lookup(["user"], "Severance", 2022, ["season_cover"], season=0)["asset_id"] == 11
    assert index.lookup(["user"], "Severance", 2022, ["season_cover"], season=1)["asset_id"] == 12
    assert index.lookup(["user"], "Severance", 2022, ["show_cover"])["asset_id"] == 10


@pytest.mark.unit
def test_lookup_tombstoned_and_parenthetical(index):
    _rec(index, "user", 1, "The Office", 2005, "show_cover")   # index stores the parsed (stripped) title
    row = index.lookup(["user"], "The Office (US)", 2005, ["show_cover"])   # query strips the suffix
    assert row is not None and row["asset_id"] == 1
    index.reconcile("user", seen_ids=set(), crawl_started_at=FAR_FUTURE)   # tombstone everything
    assert index.lookup(["user"], "The Office (US)", 2005, ["show_cover"]) is None


# ------------------------------- dedupe key --------------------------------

@pytest.mark.unit
def test_dedupe_key():
    def series(seasons):
        return WebhookEvent(kind="tv", title="Show", year=2020, tmdb_id=42, tvdb_id=7,
                            seasons=frozenset(seasons), source="sonarr")
    assert WebhookService._dedupe_key(series([1])) == WebhookService._dedupe_key(series([1]))
    assert WebhookService._dedupe_key(series([1])) != WebhookService._dedupe_key(series([2]))
    # falls back to normalized title when there is no id
    no_id = WebhookEvent(kind="movie", title="Léon", year=1994, tmdb_id=None, tvdb_id=None,
                         seasons=frozenset(), source="radarr")
    assert WebhookService._dedupe_key(no_id)[1] == "leon"


# ------------------- regression: the file_type contract (the live crash) -------------------

@pytest.mark.unit
@pytest.mark.parametrize("artwork_type,season", [
    ("movie_poster", None),
    ("show_cover", None),
    ("season_cover", 2),
])
def test_artwork_dict_carries_the_file_type_key_the_processor_reads(artwork_type, season):
    """The webhook must key the artwork type as 'file_type' - the key get_posters writes and the
       upload processor reads. Keyed as 'type' (the old bug), ARTWORK_ID_MAP.get(...) returns None
       and PlexUploader.set_artwork does None + md5, the exact 'unsupported operand type(s) for +:
       NoneType and str' that broke a real Radarr import in production."""
    row = {"title": "Dune", "author": "someuser", "year": 2021, "asset_id": 42,
           "url": "https://theposterdb.com/api/assets/42"}
    artwork = WebhookService._artwork_dict(row, "&_cb=123", artwork_type, season)

    assert artwork["file_type"] == artwork_type
    assert ARTWORK_ID_MAP.get(artwork["file_type"]) is not None

    # Reproduce the runtime path: the processor derives artwork_id from file_type and hands it to
    # the uploader, whose set_artwork builds label = artwork_id + md5(url). A None artwork_id here
    # is the crash.
    artwork_id = ARTWORK_ID_MAP.get(artwork.get("file_type"))
    artwork_type_str = ARTWORK_TYPE_MAP.get(artwork.get("file_type"))
    uploader = PlexUploader(MagicMock(), artwork_type_str, artwork_id)
    uploader.set_artwork(artwork)
    assert isinstance(uploader.label, str) and uploader.label
