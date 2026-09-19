"""cook_soup fetches through a pooled session, so a crawl reuses one connection per host."""

import threading

import pytest

from utils import soup_utils


@pytest.fixture(autouse=True)
def a_fresh_session_per_test(monkeypatch):
    monkeypatch.setattr(soup_utils, "_sessions", threading.local())


class _Response:
    status_code = 200
    text = "<html><body><h1>Poster set</h1></body></html>"

    def raise_for_status(self):
        return None


@pytest.mark.unit
def test_every_fetch_on_one_thread_uses_the_same_session(monkeypatch):
    sessions_used = []

    def record(self, url, **kwargs):
        sessions_used.append(self)
        return _Response()

    monkeypatch.setattr(soup_utils.requests.Session, "get", record)

    soup_utils.cook_soup("https://theposterdb.com/set/1")
    soup_utils.cook_soup("https://theposterdb.com/set/2")

    assert len(sessions_used) == 2
    assert sessions_used[0] is sessions_used[1]


@pytest.mark.unit
def test_the_browser_headers_are_set_on_the_session(monkeypatch):
    monkeypatch.setattr(soup_utils.requests.Session, "get", lambda self, url, **kwargs: _Response())

    soup_utils.cook_soup("https://theposterdb.com/set/1")

    assert soup_utils._session().headers["User-Agent"] == soup_utils.BROWSER_HEADERS["User-Agent"]


@pytest.mark.unit
def test_each_thread_gets_its_own_session(monkeypatch):
    monkeypatch.setattr(soup_utils.requests.Session, "get", lambda self, url, **kwargs: _Response())

    soup_utils.cook_soup("https://theposterdb.com/set/1")
    on_this_thread = soup_utils._session()

    from_other_thread = []
    worker = threading.Thread(target=lambda: from_other_thread.append(soup_utils._session()))
    worker.start()
    worker.join()

    assert from_other_thread[0] is not on_this_thread
