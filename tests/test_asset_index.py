"""Unit tests for the persistent ThePosterDB user-uploads index (services/asset_index.py)."""

import glob
from datetime import datetime, timedelta, timezone

import pytest

from services.asset_index import (
    AssetIndex,
    normalize_title,
    page_is_fully_known,
    full_crawl_due,
)

FAR_FUTURE = "2999-01-01T00:00:00+00:00"
FAR_PAST = "1999-01-01T00:00:00+00:00"


def _asset(asset_id, title="A Movie", year=2020, season=None,
           media_type="movie_poster", author="artist", url=None):
    return {
        "id": asset_id,
        "title": title,
        "year": year,
        "season": season,
        "media_type": media_type,
        "author": author,
        "url": url or f"https://theposterdb.com/api/assets/{asset_id}",
    }


@pytest.fixture
def index(tmp_path):
    return AssetIndex(str(tmp_path / "asset_index.db"))


@pytest.mark.unit
def test_schema_creation_idempotent(tmp_path):
    path = str(tmp_path / "asset_index.db")
    AssetIndex(path)
    AssetIndex(path).record("user", [_asset(1)])   # second init keeps the data, no error
    assert AssetIndex(path).known_ids("user") == {1}


@pytest.mark.unit
def test_record_upsert_and_dedupe(index):
    assert index.record("user", [_asset(1, title="First")]) == 1
    assert index.record("user", [_asset(1, title="First")]) == 0   # duplicate id collapses
    assert index.known_ids("user") == {1}
    # Tombstone then re-record: mutable fields update and the tombstone clears
    index.reconcile("user", seen_ids=set(), crawl_started_at=FAR_FUTURE)
    index.record("user", [_asset(1, title="Renamed", url="https://x/9")])
    rows = index.assets_for_user("user")
    assert len(rows) == 1
    assert rows[0]["title"] == "Renamed"
    assert rows[0]["url"] == "https://x/9"
    assert rows[0]["missing_since"] is None


@pytest.mark.unit
def test_known_ids_includes_tombstoned(index):
    index.record("user", [_asset(1), _asset(2)])
    index.reconcile("user", seen_ids={1}, crawl_started_at=FAR_FUTURE)
    assert index.known_ids("user") == {1, 2}   # 2 tombstoned but still "known"


@pytest.mark.unit
def test_assets_for_user_filters_and_order(index):
    index.record("user", [
        _asset(1, media_type="movie_poster"),
        _asset(3, media_type="movie_poster"),
        _asset(2, media_type="unknown"),
    ])
    index.record("user", [_asset(9, media_type="movie_poster")])
    index.reconcile("user", seen_ids={1, 3, 2}, crawl_started_at=FAR_FUTURE)
    ids = [r["asset_id"] for r in index.assets_for_user("user")]
    assert ids == [3, 1]   # 9 tombstoned, 2 unknown-type; remainder newest-first


@pytest.mark.unit
def test_reconcile_tombstones_and_spares(index):
    index.record("user", [_asset(1), _asset(2), _asset(3)])
    assert index.reconcile("user", seen_ids={1}, crawl_started_at=FAR_FUTURE) == 2
    assert {r["asset_id"] for r in index.assets_for_user("user")} == {1}
    # A row inserted after the crawl started is spared even when unseen
    index.record("user", [_asset(4)])
    assert index.reconcile("user", seen_ids=set(), crawl_started_at=FAR_PAST) == 0
    assert 4 in {r["asset_id"] for r in index.assets_for_user("user")}


@pytest.mark.unit
def test_crawl_state_roundtrip(index):
    assert index.crawl_state("user") is None
    index.record_crawl("user", full=True, seen_count=42)
    state = index.crawl_state("user")
    assert state["last_seen_count"] == 42
    full_ts = state["last_full_crawl"]
    assert full_ts is not None
    index.record_crawl("user", full=False, seen_count=50)   # incremental keeps last_full_crawl
    state = index.crawl_state("user")
    assert state["last_seen_count"] == 50
    assert state["last_full_crawl"] == full_ts


@pytest.mark.unit
def test_page_is_fully_known():
    assert page_is_fully_known(set(), {1, 2}) is False     # empty page never stops
    assert page_is_fully_known({1, 9}, {1, 2}) is False     # mixed page keeps crawling
    assert page_is_fully_known({1, 2}, {1, 2, 3}) is True    # fully known -> stop


@pytest.mark.unit
def test_full_crawl_due():
    now = datetime.now(timezone.utc)
    assert full_crawl_due(None, 7) is True
    assert full_crawl_due(now.isoformat(), 7) is False
    stale = (now - timedelta(days=8)).isoformat()
    assert full_crawl_due(stale, 7) is True
    assert full_crawl_due(stale, 30) is False   # 8 days old, 30-day window -> not due yet
    assert full_crawl_due("not-a-date", 7) is True


@pytest.mark.unit
def test_normalize_title():
    assert normalize_title("Mission: Impossible") == normalize_title("Mission - Impossible")
    assert normalize_title("Léon") == "leon"
    assert normalize_title("Tom & Jerry") == "tom and jerry"
    assert normalize_title("  Mad   Max 2!  ") == "mad max 2"


@pytest.mark.unit
def test_corrupt_file_self_heal(tmp_path):
    path = str(tmp_path / "asset_index.db")
    with open(path, "wb") as f:
        f.write(b"this is not a sqlite database, just garbage bytes")
    index = AssetIndex(path)                       # must self-heal, not raise
    assert glob.glob(path + ".corrupt-*")
    index.record("user", [_asset(1)])
    assert index.known_ids("user") == {1}
