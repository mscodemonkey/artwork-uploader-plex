"""Unit tests for the KometaRunner service and its helper parsing utilities."""

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.enums import FileType, RunOutcome
from kometa.kometa_runner import (
    KometaRunner,
    match_key,
    match_asset,
    match_library_name,
    parse_operations_log,
    parse_overlays_log,
    parse_applied_overlays,
    parse_error_line,
)


# ==============================================================================
# Pure Helper & Log Parsing Tests
# ==============================================================================

def test_match_library_name():
    """Verify regex extraction of library names from header logs."""
    assert match_library_name("| Applying Overlays for the TV Shows Library |") == "TV Shows"
    assert match_library_name("| Movies Library Operations |") == "Movies"
    assert match_library_name("Regular log line without headers") is None

def test_parse_operations_log():
    """Verify parsing of Kometa operation log lines for posters, season covers, and title cards."""
    # Poster / Movie
    res1 = parse_operations_log("Metadata: asset_directory updated Dune's poster to [File]")
    assert res1 == {"title": "Dune", "asset_type": "poster", "season": None, "episode": None}

    # Season Cover
    res2 = parse_operations_log("Metadata: asset_directory updated VisionQuest Season 01's poster to [File]")
    assert res2 == {"title": "VisionQuest", "asset_type": FileType.SEASON_COVER.value, "season": 1, "episode": None}

    # Title Card
    res3 = parse_operations_log("Metadata: asset_directory updated VisionQuest S01E03's poster to [File]")
    assert res3 == {"title": "VisionQuest", "asset_type": FileType.TITLE_CARD.value, "season": 1, "episode": 3}

def test_parse_overlays_log():
    """Verify title/season/episode extraction from overlay progress log lines."""
    # Real Kometa log output without episode title
    s, e = parse_overlays_log("(1/8) VisionQuest S01E01", "VisionQuest")
    assert s == 1 and e == 1

    # Real Kometa log output with year
    s_year, e_year = parse_overlays_log("(1/8) VisionQuest (2026) S01E03", "VisionQuest")
    assert s_year == 1 and e_year == 3

    # Log line with trailing episode title (future proofing)
    s_full, e_full = parse_overlays_log("(1/8) VisionQuest S01E03 Reboot", "VisionQuest")
    assert s_full == 1 and e_full == 3

    # Season cover line
    s_season, e_season = parse_overlays_log("(1/2) VisionQuest Season 01", "VisionQuest")
    assert s_season == 1 and e_season is None

    # Unrelated line
    assert parse_overlays_log("Unrelated show title line", "VisionQuest") == (None, None)

def test_parse_applied_overlays():
    """Verify regex extraction of overlay names from Kometa overlay summary lines."""
    line = "Overlay File (1) 1080p-DV, Overlay File (2) HDR10"
    overlays = parse_applied_overlays(line)
    assert overlays == ["1080p-DV", "HDR10"]

def test_match_key_and_match_asset():
    """Verify matching ratingKey and specific updated_asset entries in the library map."""
    library_map = {
        418617: {
            "title": "VisionQuest",
            "media_type": "show",
            "updated_assets": [
                {"file_type": FileType.TITLE_CARD.value, "season": 1, "episode": 3, "author": "RandalPink87"}
            ]
        }
    }

    # Match ratingKey
    key = match_key(library_map, title="VisionQuest", season=1, episode=3)
    assert key == 418617

    # Match Asset
    asset = match_asset(
        asset_list=library_map[418617]["updated_assets"],
        file_type=FileType.TITLE_CARD.value,
        season=1,
        episode=3
    )
    assert asset is not None
    assert asset["author"] == "RandalPink87"

# ==============================================================================
# Queueing & Debounce Tests
# ==============================================================================

@pytest.fixture
def sample_asset_map():
    return {
        "TV Shows": {
            418617: {
                "title": "VisionQuest",
                "year": 2026,
                "media_type": "show",
                "updated_assets": [
                    {
                        "file_type": FileType.TITLE_CARD.value,
                        "season": 1,
                        "episode": 3,
                        "author": "RandalPink87",
                        "overlay": True,
                        "status": "refreshed"
                    }
                ]
            }
        }
    }

def test_enqueue_starts_and_resets_debounce_timer(sample_asset_map):
    """Verify that enqueueing assets merges pending maps and resets the timer."""
    runner = KometaRunner()

    with patch("threading.Timer") as mock_timer_cls, \
         patch("kometa.kometa_runner.update_log"), \
         patch("kometa.kometa_runner.debug_me"):
        
        mock_timer_inst = MagicMock()
        mock_timer_cls.return_value = mock_timer_inst

        # First enqueue
        runner.enqueue(sample_asset_map)
        assert runner._timer is not None
        mock_timer_cls.assert_called_once_with(runner.debounce_seconds, runner._process_queue)
        mock_timer_inst.start.assert_called_once()

        # Second enqueue (should cancel active timer and start a new one)
        runner.enqueue(sample_asset_map)
        mock_timer_inst.cancel.assert_called_once()
        assert mock_timer_inst.start.call_count == 2

@patch("threading.Thread")
def test_process_queue_launches_execution_thread(mock_thread_cls, sample_asset_map):
    """Verify _process_queue snapshots pending_map, sets _is_running, and launches batch worker."""
    runner = KometaRunner()
    runner._pending_map = sample_asset_map.copy()

    runner._process_queue()

    assert runner._is_running is True
    assert runner._pending_map == {}  # Map should be cleared after snapshot
    mock_thread_cls.assert_called_once()

# ==============================================================================
# YAML Generation Tests
# ==============================================================================

def test_generate_targeted_yaml_updates_settings_and_filters_libraries(tmp_path):
    """Verify generate_targeted_yaml creates temp config with optimization flags and stripped collections."""
    runner = KometaRunner()
    
    # Mock config path
    config_dir = tmp_path / "kometa_config"
    config_dir.mkdir()
    main_yml = config_dir / "config.yml"
    
    initial_yaml = """
libraries:
  TV Shows:
    collection_files:
      - file: config/collections.yml
    operations:
      assets_for_all_collections: true
  Movies:
    collection_files:
      - file: config/movies_collections.yml
settings:
  cache: true
"""
    main_yml.write_text(initial_yaml, encoding="utf-8")

    batch_map = {
        "TV Shows": {
            418617: {"title": "VisionQuest", "updated_assets": []}
        }
    }

    with patch.object(KometaRunner, "config_path", config_dir):
        temp_path = runner.generate_targeted_yaml(batch_map)

        assert temp_path.exists()
        assert temp_path.name == "temp_kometa_run.yml"
        
        # Read back generated YAML to verify settings
        import yaml
        with open(temp_path, "r", encoding="utf-8") as f:
            generated = yaml.safe_load(f)

        assert generated["settings"]["show_unmanaged"] is False
        assert generated["settings"]["show_unconfigured"] is False
        assert generated["settings"]["run_order"] == ["operations", "overlays"]
        assert "TV Shows" in generated["libraries"]
        assert "Movies" not in generated["libraries"]  # Unused library should be popped
        assert "collection_files" not in generated["libraries"]["TV Shows"]


# ==============================================================================
# Subprocess Execution & Command Tests
# ==============================================================================

@patch("subprocess.Popen")
@patch("kometa.kometa_runner.RunHistory")
def test_run_kometa_process_executes_docker_command_and_logs_history(
    mock_run_history_cls, mock_popen, tmp_path, sample_asset_map
):
    """Verify _run_kometa_process formats docker exec correctly and records successful runs in RunHistory."""
    runner = KometaRunner()
    runner._kometa_libraries = ["TV Shows"]

    mock_proc = MagicMock()
    # Mock log lines matching the exact sequence KometaRunner expects:
    mock_proc.stdout = [
        "| TV Shows Library Operations |\n",
        "Metadata: asset_directory updated VisionQuest S01E03's poster to [File]\n",
        "| Applying Overlays for the TV Shows Library |\n",
        "(1/2) VisionQuest S01E03\n",
        "   Overlays Applied: Overlay File (1) 1080p-DV\n",
        "(2/2) VisionQuest S01E09\n",
        "   Overlays Applied: Overlay File (1) 1080p-DV-HDR\n",
    ]
    mock_proc.wait.return_value = None
    mock_proc.returncode = 0
    mock_popen.return_value = mock_proc

    mock_history_instance = MagicMock()
    mock_run_history_cls.return_value = mock_history_instance

    temp_config = tmp_path / "temp_kometa_run.yml"
    temp_config.write_text("libraries: {}", encoding="utf-8")

    with (
        patch("kometa.kometa_runner.update_log"),
        patch("kometa.kometa_runner.log_to_file"),
        patch.object(KometaRunner, "container_name", "kometa"),
    ):
        runner._run_kometa_process(temp_config, sample_asset_map)

    assert mock_popen.call_count >= 1

    last_cmd = mock_popen.call_args[0][0]
    cmd_str = " ".join(last_cmd)

    assert "docker exec" in cmd_str
    assert "kometa" in cmd_str
    assert "python kometa.py" in cmd_str
    assert "KOMETA_RUN_LIBRARIES=TV Shows" in cmd_str
    assert "KOMETA_MODE=items(plex:418617)" in cmd_str

    assert mock_history_instance.add_run.call_count >= 1
    first_run_call = mock_history_instance.add_run.call_args_list[0].kwargs
    assert first_run_call["outcome"] == RunOutcome.SUCCESS.value
    assert first_run_call["assets_processed"] == 1

# ==============================================================================
# Lock & Disk Cleanup Tests
# ==============================================================================

def test_is_running_detects_in_memory_and_disk_lock(tmp_path):
    """Verify is_running returns True if _is_running is True OR if temp_kometa_run.yml exists."""
    runner = KometaRunner()

    config_dir = tmp_path / "kometa_config"
    config_dir.mkdir()
    temp_yaml = config_dir / "temp_kometa_run.yml"

    with patch.object(KometaRunner, "config_path", config_dir):
        # 1. Idle state
        runner._is_running = False
        assert runner.is_running is False

        # 2. In-memory flag active
        runner._is_running = True
        assert runner.is_running is True

        # 3. In-memory flag clear, but disk config file present (e.g. CLI run active)
        runner._is_running = False
        temp_yaml.write_text("libraries: {}", encoding="utf-8")
        assert runner.is_running is True

        # 4. Cleanup releases lock state
        temp_yaml.unlink()
        assert runner.is_running is False

def test_execute_batch_job_cleans_up_temp_files_on_failure(tmp_path, sample_asset_map):
    """Verify _execute_batch_job cleans up both the temp YAML and Kometa cache files."""
    runner = KometaRunner()

    config_dir = tmp_path / "kometa_config"
    config_dir.mkdir()

    main_yaml = config_dir / "config.yml"
    main_yaml.write_text("libraries:\n  TV Shows: {}\n", encoding="utf-8")

    temp_cache = config_dir / "temp_kometa_run.cache"
    temp_cache_wal = config_dir / "temp_kometa_run.cache-wal"

    def _simulate_kometa_creating_cache(*_args, **_kwargs):
        temp_cache.write_text("sqlite data", encoding="utf-8")
        temp_cache_wal.write_text("wal data", encoding="utf-8")
        raise RuntimeError("Subprocess failed")

    with (
        patch.object(KometaRunner, "config_path", config_dir),
        patch.object(
            KometaRunner,
            "_run_kometa_process",
            side_effect=_simulate_kometa_creating_cache,
        ),
        patch("kometa.kometa_runner.update_log"),
        patch("kometa.kometa_runner.debug_me"),
    ):
        runner._execute_batch_job(sample_asset_map)

        assert runner._is_running is False
        assert not (config_dir / "temp_kometa_run.yml").exists()
        assert not temp_cache.exists()
        assert not temp_cache_wal.exists()

def test_process_queue_re_debounces_when_already_running(sample_asset_map):
    """Verify _process_queue increments attempts and schedules a retry timer if Kometa is busy."""
    runner = KometaRunner()
    runner._pending_map = sample_asset_map.copy()

    with patch.object(KometaRunner, "is_running", True), \
         patch("threading.Timer") as mock_timer_cls, \
         patch("kometa.kometa_runner.update_log"), \
         patch("kometa.kometa_runner.debug_me"):

        mock_timer_inst = MagicMock()
        mock_timer_cls.return_value = mock_timer_inst

        runner._process_queue()

        assert runner._attempts == 1
        mock_timer_cls.assert_called_once_with(runner.debounce_seconds, runner._process_queue)
        mock_timer_inst.start.assert_called_once()
        assert len(runner._pending_map) == 1  # Batch preserved for retry

def test_process_queue_aborts_after_max_retries(sample_asset_map):
    """Verify _process_queue stops retrying and resets attempts after 3 failed attempts."""
    runner = KometaRunner()
    runner._pending_map = sample_asset_map.copy()
    runner._attempts = 3  # Simulate 3 prior retries

    with patch.object(KometaRunner, "is_running", True), \
         patch("threading.Timer") as mock_timer_cls, \
         patch("kometa.kometa_runner.update_log") as mock_update_log, \
         patch("kometa.kometa_runner.debug_me"):

        runner._process_queue()

        assert runner._attempts == 0
        mock_timer_cls.assert_not_called()  # Should not schedule another timer
        assert "after 3" in mock_update_log.call_args[0][1]

# ==============================================================================
# Error Line Parsing Tests
# ==============================================================================

@pytest.mark.parametrize(
    "log_line, container_name, expected_error",
    [
        # Non-existent container
        (
            "Error: No such container: kometa-banana",
            "kometa-banana",
            "Container 'kometa-banana' does not exist",
        ),
        (
            "Error response from daemon: No such container: kometa",
            "kometa",
            "Container 'kometa' does not exist",
        ),
        # Stopped container
        (
            "Error response from daemon: Container 8f9a2b1c3d4e is not running",
            "kometa",
            "Container 'kometa' is not running",
        ),
        (
            "Error response from daemon: container kometa is not running",
            "kometa",
            "Container 'kometa' is not running",
        ),
        # Wrong container (Python exists, kometa.py does not)
        (
            "python: can't open file '/app/kometa.py': [Errno 2] No such file or directory",
            "erugo",
            "Can't find 'kometa.py' in container 'erugo'",
        ),
        # Wrong container (Python binary missing from PATH)
        (
            'OCI runtime exec failed: exec failed: unable to start container process: exec: "python": executable file not found in $PATH',
            "plex",
            "Can't find 'kometa.py' in container 'plex'",
        ),
        # Normal / unrelated Kometa log output should return None
        (
            "| (1/8) VisionQuest S01E01 |",
            "kometa",
            None,
        ),
        (
            "Metadata: asset_directory updated VisionQuest S01E01's poster to [File]",
            "kometa",
            None,
        ),
        (
            "",
            "kometa",
            None,
        ),
    ],
)
def test_parse_error_line(log_line, container_name, expected_error):
    """Verify parse_error_line maps Docker CLI and container runtime errors to user-friendly messages."""
    assert parse_error_line(log_line, container_name) == expected_error