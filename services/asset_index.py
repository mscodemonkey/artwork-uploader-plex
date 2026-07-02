"""
Persistent index of ThePosterDB users' uploads.

A small SQLite database (one file in the config directory) that mirrors the assets a
ThePosterDB user has uploaded. Repeat scrapes of that user then only need to fetch pages
until they reach uploads that are already indexed, and other features can look cached
artwork up by title.
"""

import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timezone
from typing import List, Optional, Set

from core.constants import ASSET_INDEX_PATH


def normalize_title(title: str) -> str:
    """Lowercase, strip accents and punctuation so titles compare equal regardless of styling,
       e.g. 'Mission: Impossible' vs 'Mission - Impossible', 'Léon' vs 'Leon'."""
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    title = title.casefold().replace("&", " and ")
    title = re.sub(r"[^\w\s]", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def _now() -> str:
    """Current time as an ISO-8601 UTC string - sortable and comparable as plain text."""
    return datetime.now(timezone.utc).isoformat()


_CREATE_ASSETS = """
    CREATE TABLE IF NOT EXISTS user_assets (
        user_key      TEXT    NOT NULL,
        asset_id      INTEGER NOT NULL,
        title         TEXT,
        title_key     TEXT,
        year          INTEGER,
        season        INTEGER,
        media_type    TEXT,
        author        TEXT,
        url           TEXT,
        first_seen    TEXT,
        last_seen     TEXT,
        missing_since TEXT,
        PRIMARY KEY (user_key, asset_id)
    )
"""

_CREATE_ASSETS_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_user_assets_title
        ON user_assets (title_key, media_type)
"""

_CREATE_CRAWLS = """
    CREATE TABLE IF NOT EXISTS user_crawls (
        user_key        TEXT PRIMARY KEY,
        last_full_crawl TEXT,
        last_crawl      TEXT,
        last_seen_count INTEGER
    )
"""


class AssetIndex:
    """
    Persistent index of ThePosterDB users' uploads (SQLite, one file in the config
    directory). Writers are the scrape thread; readers may run on other threads, so the
    connection is short-lived per call and the database runs in WAL mode.
    """

    def __init__(self, path: str = ASSET_INDEX_PATH) -> None:
        self.path = path
        try:
            self._ensure_schema()
        except sqlite3.DatabaseError as e:
            # debug_me lives in utils.notifications, which imports the services package - import
            # it lazily here to avoid a start-up import cycle when the scraper pulls in the index.
            from utils.notifications import debug_me
            # The file exists but is not a valid SQLite database (corruption, a truncated
            # write on a flaky filesystem, ...). Preserve it for inspection and start clean:
            # the next crawl repopulates it, nothing is lost that a scrape can't rebuild.
            corrupt = f"{self.path}.corrupt-{int(time.time())}"
            try:
                os.rename(self.path, corrupt)
            except OSError:
                debug_me(f"Asset index at '{self.path}' is unreadable ({e}) and could not be "
                         f"moved aside; giving up on the cache.", "AssetIndex")
                raise
            debug_me(f"Asset index at '{self.path}' was unreadable ({e}); moved it to "
                     f"'{corrupt}' and started a fresh index.", "AssetIndex")
            self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA user_version = 1")
            conn.execute(_CREATE_ASSETS)
            conn.execute(_CREATE_ASSETS_INDEX)
            conn.execute(_CREATE_CRAWLS)
            conn.commit()
        finally:
            conn.close()

    def known_ids(self, user_key: str) -> Set[int]:
        """Every asset id on record for the user, tombstoned ones included, so the stop rule
           stays conservative (a re-listed deleted asset still counts as already known)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT asset_id FROM user_assets WHERE user_key = ?", (user_key,)
            ).fetchall()
        finally:
            conn.close()
        return {row["asset_id"] for row in rows}

    def record(self, user_key: str, assets: List[dict]) -> int:
        """Upsert a batch of raw (pre-filter) assets for a user, returning how many were not
           already indexed - the count the upload-count ledger checks against ThePosterDB."""
        if not assets:
            return 0
        now = _now()
        known = self.known_ids(user_key)
        rows = []
        new_count = 0
        for asset in assets:
            try:
                asset_id = int(asset["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if asset_id not in known:
                new_count += 1
                known.add(asset_id)
            title = asset.get("title")
            season = asset.get("season")
            rows.append((
                user_key, asset_id, title, normalize_title(title) if title else "",
                asset.get("year"), season if isinstance(season, int) else None,
                asset.get("media_type"), asset.get("author"), asset.get("url"), now, now,
            ))
        if not rows:
            return 0
        conn = self._connect()
        try:
            conn.executemany(
                """
                INSERT INTO user_assets
                    (user_key, asset_id, title, title_key, year, season, media_type,
                     author, url, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_key, asset_id) DO UPDATE SET
                    title=excluded.title, title_key=excluded.title_key, year=excluded.year,
                    season=excluded.season, media_type=excluded.media_type,
                    author=excluded.author, url=excluded.url, last_seen=excluded.last_seen,
                    missing_since=NULL
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()
        return new_count

    def assets_for_user(self, user_key: str) -> List[sqlite3.Row]:
        """Live (non-tombstoned, known-media-type) assets for the user, newest first - the
           order a full crawl produces."""
        conn = self._connect()
        try:
            return conn.execute(
                """
                SELECT * FROM user_assets
                WHERE user_key = ? AND missing_since IS NULL AND media_type != 'unknown'
                ORDER BY asset_id DESC
                """,
                (user_key,),
            ).fetchall()
        finally:
            conn.close()

    def reconcile(self, user_key: str, seen_ids: Set[int], crawl_started_at: str) -> int:
        """After a clean full crawl, tombstone assets that weren't seen (deleted from the
           user's uploads), sparing any row inserted since the crawl began so an overlapping
           scrape's fresh uploads are never tombstoned. Returns the number tombstoned."""
        conn = self._connect()
        try:
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS seen (asset_id INTEGER PRIMARY KEY)")
            conn.execute("DELETE FROM seen")
            conn.executemany("INSERT OR IGNORE INTO seen (asset_id) VALUES (?)",
                             [(asset_id,) for asset_id in seen_ids])
            cursor = conn.execute(
                """
                UPDATE user_assets SET missing_since = ?
                WHERE user_key = ? AND missing_since IS NULL
                    AND asset_id NOT IN (SELECT asset_id FROM seen)
                    AND last_seen < ?
                """,
                (_now(), user_key, crawl_started_at),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def crawl_state(self, user_key: str) -> Optional[sqlite3.Row]:
        """The user's crawl bookkeeping row (last full/any crawl, last upload count), or None."""
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT * FROM user_crawls WHERE user_key = ?", (user_key,)
            ).fetchone()
        finally:
            conn.close()

    def record_crawl(self, user_key: str, full: bool, seen_count: int) -> None:
        """Update the crawl ledger. last_full_crawl only advances on a full crawl."""
        now = _now()
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT last_full_crawl FROM user_crawls WHERE user_key = ?", (user_key,)
            ).fetchone()
            last_full = now if full else (existing["last_full_crawl"] if existing else None)
            conn.execute(
                """
                INSERT INTO user_crawls (user_key, last_full_crawl, last_crawl, last_seen_count)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_key) DO UPDATE SET
                    last_full_crawl=excluded.last_full_crawl,
                    last_crawl=excluded.last_crawl,
                    last_seen_count=excluded.last_seen_count
                """,
                (user_key, last_full, now, seen_count),
            )
            conn.commit()
        finally:
            conn.close()


def page_is_fully_known(page_ids: Set[int], known_ids: Set[int]) -> bool:
    """Incremental stop rule: a page halts the crawl only if it had assets and every one was
       already in the index. A page with any new asset (even mixed with known ones) keeps the
       crawl going, which is why the rule is page- rather than item-granular - ThePosterDB
       pages are newest-first by upload batch but not strictly by id within a batch."""
    return bool(page_ids) and page_ids <= known_ids


def full_crawl_due(last_full_crawl: Optional[str], refresh_days: int) -> bool:
    """True when the user has never had a full crawl or the last one is at least refresh_days
       old - the next scrape then re-crawls every page to catch edits and deletions."""
    if not last_full_crawl:
        return True
    try:
        last = datetime.fromisoformat(last_full_crawl)
    except (TypeError, ValueError):
        return True
    return (datetime.now(timezone.utc) - last).total_seconds() >= refresh_days * 86400
