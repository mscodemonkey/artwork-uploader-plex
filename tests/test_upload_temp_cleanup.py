"""A ZIP upload must not leave its temporary directories behind.

save_uploaded_file makes two: one holding the uploaded archive, one holding every image extracted
from it. They used to survive a cancelled run and a failed one, and accumulated for the life of
the container.
"""

import os
import tempfile

import pytest

import artwork_uploader
import core.globals as app_globals
import web_routes
from models.instance import Instance


@pytest.fixture
def upload(tmp_path, monkeypatch):
    """Drives save_uploaded_file with the extraction and the processing stubbed out."""
    created = []
    real_mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        created.append(path)
        return path

    monkeypatch.setattr(web_routes.tempfile, "mkdtemp", recording_mkdtemp)
    monkeypatch.setattr(web_routes, "update_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(web_routes, "update_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(web_routes, "notify_web", lambda *args, **kwargs: None)
    monkeypatch.setattr(web_routes, "RunHistory", lambda: _NullRunHistory())
    monkeypatch.setattr(app_globals, "cancel_scrape", False)
    monkeypatch.setattr(app_globals, "scrapes_running", 1)

    def extract(instance, zip_path, extract_dir, *args, **kwargs):
        with open(os.path.join(extract_dir, "poster.jpg"), "wb") as extracted:
            extracted.write(b"an image")
        return [], 0, "", "", ""

    monkeypatch.setattr(web_routes, "extract_and_list_zip", extract)
    monkeypatch.setattr(artwork_uploader, "process_uploaded_artwork", lambda *args, **kwargs: None)

    def run():
        source = tmp_path / "chunked-upload"
        source.write_bytes(b"a zip file")
        web_routes.save_uploaded_file(
            Instance(broadcast=True),
            "set.zip",
            [],
            [],
            "",
            None,
            {"set.zip": {"temp_path": str(source)}},
            web_routes.re.compile(r".*"),
            lambda path: "portrait",
            lambda artwork: 0,
        )

    return run, created


class _NullRunHistory:
    def add_run(self, **kwargs):
        return None


@pytest.mark.unit
def test_a_finished_upload_removes_both_temporary_directories(upload):
    run, created = upload

    run()

    assert len(created) == 2
    assert [path for path in created if os.path.exists(path)] == []


@pytest.mark.unit
def test_a_cancelled_upload_removes_both_temporary_directories(upload, monkeypatch):
    run, created = upload

    def extract_then_cancel(instance, zip_path, extract_dir, *args, **kwargs):
        with open(os.path.join(extract_dir, "poster.jpg"), "wb") as extracted:
            extracted.write(b"an image")
        monkeypatch.setattr(app_globals, "cancel_scrape", True)
        return [], 0, "", "", ""

    monkeypatch.setattr(web_routes, "extract_and_list_zip", extract_then_cancel)

    run()

    assert len(created) == 2
    assert [path for path in created if os.path.exists(path)] == []


@pytest.mark.unit
def test_a_failed_upload_removes_both_temporary_directories(upload, monkeypatch):
    run, created = upload

    def boom(*args, **kwargs):
        raise RuntimeError("Plex went away")

    monkeypatch.setattr(artwork_uploader, "process_uploaded_artwork", boom)

    with pytest.raises(RuntimeError):
        run()

    assert len(created) == 2
    assert [path for path in created if os.path.exists(path)] == []
