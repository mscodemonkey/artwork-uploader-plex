"""
The per-run log file follows the run, not the process.

Every run writes its own file under the logs directory and its history record points at
it. Runs overlap all the time on a busy server: a Radarr or Sonarr import lands while a
scheduled bulk import is hours from finishing. Each run keeps its own file through that,
and a run that continues on another thread (a webhook retry, a chunked upload) carries its
file across the hop.
"""

import os
import threading

import pytest

import core.globals as globals
import services.run_history as run_history_module
import utils.notifications as notifications
from models.instance import Instance
from services.run_history import RunHistory
from utils.notifications import current_log_file, log_to_file, resume_log_file, update_log


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(notifications, "DEFAULT_LOG_PATH", str(log_dir))
    monkeypatch.setattr(run_history_module, "DEFAULT_LOG_PATH", str(log_dir))
    return log_dir


@pytest.fixture
def history(tmp_path):
    return RunHistory(str(tmp_path / "run_history.json"))


@pytest.fixture(autouse=True)
def no_log_on_the_test_thread():
    globals.run_log.path = None
    yield
    globals.run_log.path = None


def _record(history, run_type, label):
    history.add_run(
        run_type=run_type,
        label=label,
        started_at="2026-09-05T00:00:00+00:00",
        ended_at="2026-09-05T00:01:00+00:00",
        trigger="manual",
        outcome="success",
    )


def _on_a_thread(target):
    """Run `target` to completion on its own thread, the way a webhook or a schedule does."""
    thread = threading.Thread(target=target)
    thread.start()
    thread.join()


@pytest.mark.unit
def test_a_run_finishing_mid_way_through_another_leaves_that_run_its_log(log_dir, history):
    """The bug this guards against: a webhook import that finished during a bulk import used
    to record the bulk run's file as its own and switch the bulk run's logging off, so the
    long run, the one worth reading, ended with no log at all."""
    bulk = Instance(mode="cli")
    bulk_log = log_to_file("bulk_import_full.txt")
    update_log(bulk, "bulk line one")

    def webhook_import():
        webhook_log = log_to_file("webhook_Dune_2021")
        assert webhook_log != bulk_log
        update_log(Instance(mode="cli"), "webhook line")
        _record(history, "webhook", "Dune (2021)")
        assert current_log_file() is None, "recording the run ends its own logging"

    _on_a_thread(webhook_import)

    assert current_log_file() == bulk_log, "the other run's finish must not touch this one"
    update_log(bulk, "bulk line two")
    _record(history, "bulk", "bulk_import_full.txt")

    runs = {run["run_type"]: run for run in history.get_runs()}
    assert runs["bulk"]["log_file"] == os.path.basename(bulk_log)
    assert runs["webhook"]["log_file"] != runs["bulk"]["log_file"]
    assert runs["webhook"]["log_file"] != ""

    bulk_text = (log_dir / runs["bulk"]["log_file"]).read_text(encoding="utf-8")
    assert "bulk line one" in bulk_text and "bulk line two" in bulk_text
    assert "webhook line" not in bulk_text
    assert "webhook line" in (log_dir / runs["webhook"]["log_file"]).read_text(encoding="utf-8")


@pytest.mark.unit
def test_a_run_keeps_the_file_it_opened_first(log_dir):
    """A scheduled import asks for its log twice on the way in, once from the schedule and
    once from the import itself. It gets one file."""
    first = log_to_file("bulk_import_fast.txt")
    second = log_to_file("bulk_import_fast.txt")
    assert first == second
    assert current_log_file() == first


@pytest.mark.unit
def test_resume_carries_a_run_onto_the_thread_that_continues_it(log_dir, history):
    """A webhook retry and a later upload chunk each run on a fresh thread, which starts with
    no log file. Resuming the path there keeps the whole run in one file."""
    opened_on = log_to_file("webhook_Dune_2021")
    update_log(Instance(mode="cli"), "first attempt")

    def later_attempt():
        assert current_log_file() is None, "a new thread starts outside any run"
        resume_log_file(opened_on)
        update_log(Instance(mode="cli"), "second attempt")
        _record(history, "webhook", "Dune (2021)")

    _on_a_thread(later_attempt)

    assert history.get_runs()[0]["log_file"] == os.path.basename(opened_on)
    text = (log_dir / os.path.basename(opened_on)).read_text(encoding="utf-8")
    assert "first attempt" in text and "second attempt" in text


@pytest.mark.unit
def test_a_run_recorded_with_no_log_file_records_an_empty_name(history):
    _record(history, "bulk", "bulk_import.txt")
    assert history.get_runs()[0]["log_file"] == ""


@pytest.mark.unit
def test_a_scrape_url_short_of_three_parts_still_opens_a_log(log_dir):
    """A URL with two path parts, the kind you get from trimming the id off the end, used to
    raise a NameError here. That landed inside the run, after the scrape had been counted as
    running, so a mistyped URL took the run down rather than being reported as a bad URL."""
    path = log_to_file("https://theposterdb.com/poster")

    assert current_log_file() == path
    assert os.path.dirname(path) == str(log_dir), "the log belongs in the log directory, not under a path built out of the URL"

    update_log(Instance(mode="cli"), "short url line")
    assert "short url line" in (log_dir / os.path.basename(path)).read_text(encoding="utf-8")
    assert "theposterdb.com_poster" in os.path.basename(path), "the parts the URL does have still name the run"


@pytest.mark.unit
def test_a_full_scrape_url_is_named_after_its_source_type_and_id(log_dir):
    """The naming the short URL above falls back from: a whole URL reads as a source, a type
    and an id, so the log is recognisable in the directory without opening it."""
    path = log_to_file("https://theposterdb.com/set/12345")
    assert os.path.basename(path).endswith("_scrape_tpdb_set_12345.log")

@pytest.mark.unit
def test_a_scrape_url_with_an_unknown_asset_type_still_opens_a_log(log_dir):
    """An asset type the URL map does not carry, an artist page or a MediUX collection, used to
    crash three lines below the short URL case: the fallback was a string and the next line
    called .get on it. Same place inside the run, same lost run."""
    path = log_to_file("https://theposterdb.com/artist/123")

    assert current_log_file() == path
    assert os.path.basename(path).endswith("_scrape_tpdb_unknown_url_type_123.log")
