"""
Covers the run history record parse_bulk_file_from_cli writes.

A bulk import run from the command line reaches none of the recording sites the web
interface uses, so it needs its own coverage: a clean run, a run whose lines error, a
run where the file has nothing worth doing, a missing file, and a run that dies on an
unexpected exception part way through.
"""

from unittest.mock import patch

import pytest

from artwork_uploader import parse_bulk_file_from_cli
from models.instance import Instance
from services.run_history import RunHistory
from core.enums import RunOutcome, RunTrigger, RunType

OUTCOME_SUCCESS = RunOutcome.SUCCESS.value
OUTCOME_PARTIAL = RunOutcome.PARTIAL.value
OUTCOME_FAILED = RunOutcome.FAILED.value
OUTCOME_SKIPPED = RunOutcome.SKIPPED.value

URL = "https://mediux.pro/sets/12345"


@pytest.fixture
def history(tmp_path, monkeypatch):
    real_history = RunHistory(str(tmp_path / "run_history.json"))
    monkeypatch.setattr("artwork_uploader.RunHistory", lambda: real_history)
    return real_history


@pytest.fixture
def bulk_file(tmp_path):
    def write(contents, name="nightly.txt"):
        path = tmp_path / name
        path.write_text(contents, encoding="utf-8")
        return str(path)
    return write


def _quiet():
    """The CLI writes its progress to stdout, which the tests don't need to see."""
    return (
        patch("artwork_uploader.update_log"),
        patch("artwork_uploader.debug_me"),
    )


@pytest.mark.unit
def test_successful_run_is_recorded_with_its_counters(history, bulk_file):
    def fake_scrape(instance, url, options, bulk, success_counter, assets_processed,
                    cached_counter=None, locked_counter=None, failed_counter=None):
        assets_processed[0] += 1
        success_counter[0] += 1
        cached_counter[0] += 1

    quiet_log, quiet_debug = _quiet()
    with patch("artwork_uploader.scrape_and_upload", side_effect=fake_scrape), quiet_log, quiet_debug:
        parse_bulk_file_from_cli(Instance(mode="cli"), bulk_file(f"{URL}\n{URL}\n"))

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["run_type"] == RunType.BULK.value
    assert runs[0]["trigger"] == RunTrigger.CLI.value
    assert runs[0]["outcome"] == OUTCOME_SUCCESS
    assert runs[0]["assets_processed"] == 2
    assert runs[0]["success_count"] == 2
    assert runs[0]["cached_count"] == 2
    assert runs[0]["error_count"] == 0


@pytest.mark.unit
def test_the_label_is_the_file_name_not_the_whole_path(history, bulk_file):
    """The history table shows the label as it is, so a full container path would be unreadable."""
    quiet_log, quiet_debug = _quiet()
    with patch("artwork_uploader.scrape_and_upload"), quiet_log, quiet_debug:
        parse_bulk_file_from_cli(Instance(mode="cli"), bulk_file(f"{URL}\n", name="weekly.txt"))

    assert history.get_runs()[0]["label"] == "weekly.txt"


@pytest.mark.unit
def test_counters_survive_the_whole_file(history, bulk_file):
    """Every line adds to the same counters, rather than each line starting from zero."""
    def fake_scrape(instance, url, options, bulk, success_counter, assets_processed,
                    cached_counter=None, locked_counter=None, failed_counter=None):
        assets_processed[0] += 2
        success_counter[0] += 1
        locked_counter[0] += 1

    quiet_log, quiet_debug = _quiet()
    with patch("artwork_uploader.scrape_and_upload", side_effect=fake_scrape), quiet_log, quiet_debug:
        parse_bulk_file_from_cli(Instance(mode="cli"), bulk_file(f"{URL}\n{URL}\n{URL}\n"))

    runs = history.get_runs()
    assert runs[0]["assets_processed"] == 6
    assert runs[0]["success_count"] == 3
    assert runs[0]["locked_count"] == 3


@pytest.mark.unit
def test_a_line_that_fails_to_scrape_is_recorded_as_partial(history, bulk_file):
    from core.exceptions import ScraperException

    quiet_log, quiet_debug = _quiet()
    with patch("artwork_uploader.scrape_and_upload", side_effect=ScraperException("bad set")), quiet_log, quiet_debug:
        parse_bulk_file_from_cli(Instance(mode="cli"), bulk_file(f"{URL}\n"))

    runs = history.get_runs()
    assert runs[0]["outcome"] == OUTCOME_PARTIAL
    assert runs[0]["error_count"] == 1


@pytest.mark.unit
def test_an_upload_that_exhausted_its_retries_counts_as_an_error(history, bulk_file):
    """The line itself scraped fine, so only failed_counter says anything went wrong."""
    def fake_scrape(instance, url, options, bulk, success_counter, assets_processed,
                    cached_counter=None, locked_counter=None, failed_counter=None):
        assets_processed[0] += 1
        failed_counter[0] += 1

    quiet_log, quiet_debug = _quiet()
    with patch("artwork_uploader.scrape_and_upload", side_effect=fake_scrape), quiet_log, quiet_debug:
        parse_bulk_file_from_cli(Instance(mode="cli"), bulk_file(f"{URL}\n"))

    runs = history.get_runs()
    assert runs[0]["outcome"] == OUTCOME_PARTIAL
    assert runs[0]["error_count"] == 1


@pytest.mark.unit
def test_an_unusable_line_is_recorded_as_an_error_without_scraping(history, bulk_file):
    quiet_log, quiet_debug = _quiet()
    with patch("artwork_uploader.scrape_and_upload") as mock_scrape, quiet_log, quiet_debug:
        parse_bulk_file_from_cli(Instance(mode="cli"), bulk_file("not a url at all\n"))

    mock_scrape.assert_not_called()
    runs = history.get_runs()
    assert runs[0]["outcome"] == OUTCOME_PARTIAL
    assert runs[0]["error_count"] == 1


@pytest.mark.unit
def test_a_file_with_nothing_to_do_is_recorded_as_skipped(history, bulk_file):
    quiet_log, quiet_debug = _quiet()
    with patch("artwork_uploader.scrape_and_upload") as mock_scrape, quiet_log, quiet_debug:
        parse_bulk_file_from_cli(Instance(mode="cli"), bulk_file("# parked for now\n// and this one\n\n"))

    mock_scrape.assert_not_called()
    runs = history.get_runs()
    assert runs[0]["outcome"] == OUTCOME_SKIPPED
    assert runs[0]["assets_processed"] == 0
    assert runs[0]["error_count"] == 0


@pytest.mark.unit
def test_a_missing_file_is_recorded_as_failed(history, tmp_path):
    quiet_log, quiet_debug = _quiet()
    with patch("artwork_uploader.scrape_and_upload") as mock_scrape, quiet_log, quiet_debug:
        parse_bulk_file_from_cli(Instance(mode="cli"), str(tmp_path / "gone.txt"))

    mock_scrape.assert_not_called()
    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_FAILED
    assert runs[0]["label"] == "gone.txt"


@pytest.mark.unit
def test_an_unexpected_exception_mid_run_is_still_recorded(history, bulk_file):
    """The run is recorded on the way out, so a crash leaves a record rather than a silence."""
    quiet_log, quiet_debug = _quiet()
    with (
        patch("artwork_uploader.scrape_and_upload"),
        patch("artwork_uploader.elapsed_time", side_effect=RuntimeError("boom")),
        quiet_log,
        quiet_debug,
    ):
        with pytest.raises(RuntimeError):
            parse_bulk_file_from_cli(Instance(mode="cli"), bulk_file(f"{URL}\n"))

    runs = history.get_runs()
    assert len(runs) == 1
    assert runs[0]["outcome"] == OUTCOME_FAILED
