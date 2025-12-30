# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Artwork Uploader for Plex is a Flask-based web application that automates uploading artwork (posters, backgrounds, title cards) from ThePosterDB and MediUX to Plex Media Server. The application uses a layered architecture with a service layer for business logic, scraper modules for fetching artwork, and Plex integration for uploading.

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Install development dependencies (testing, linting, type checking)
pip install -r requirements-dev.txt
```

### Running the Application
```bash
# Activate venv first (if using)
source .venv/bin/activate

# Start web server (default port 4567)
python artwork_uploader.py

# Use a custom config file
python artwork_uploader.py --config /path/to/custom-config.json

# Single URL scrape
python artwork_uploader.py https://mediux.pro/sets/9242

# Bulk import from file
python artwork_uploader.py bulk bulk_import.txt

# Bulk import with custom config
python artwork_uploader.py bulk bulk_import.txt --config /path/to/custom-config.json
```

### Docker
```bash
# Build and run with docker-compose
docker compose up -d

# Use custom config via environment variable
CONFIG_PATH=/artwork-uploader/custom-config.json docker compose up -d

# Build multi-platform images (using Makefile)
make docker-build

# Release to registry
make docker-release
```

### Testing
```bash
# Run tests with pytest
pytest

# Run with coverage
pytest --cov

# Run specific test markers
pytest -m unit          # Unit tests only
pytest -m "not slow"    # Skip slow tests
```

### Code Quality
```bash
# Format code
black .

# Sort imports
isort .

# Type checking
mypy artwork_uploader.py

# Linting
flake8 .
pylint artwork_uploader.py
```

## Architecture

### High-Level Structure

The application follows a layered architecture:

```
Web UI (Flask + SocketIO)
    ↓
Main Application Layer (artwork_uploader.py, web_routes.py)
    ↓
Service Layer (services/)
    ↓
Business Logic (scrapers/, processors/, plex/)
    ↓
External APIs (PlexAPI, ThePosterDB, MediUX)
```

### Key Architectural Patterns

1. **Service Layer Pattern**: Business logic is encapsulated in service classes (`BulkFileService`, `ImageService`, `ArtworkProcessor`, `SchedulerService`, `UpdateService`, `UtilityService`) that are independent of UI concerns.

2. **Callback Pattern**: Services use `ProcessingCallbacks` dataclass to communicate with UI without tight coupling. Each service method accepts optional callbacks for status updates, logging, and progress.

3. **Dependency Injection**: Services receive dependencies explicitly through constructors rather than using global state.

4. **Scraper Abstraction**: Base `Scraper` class determines provider (ThePosterDB vs MediUX) from URL and delegates to specialized scrapers (`ThePosterDBScraper`, `MediuxScraper`).

### Critical Components

**PlexConnector** (`plex/plex_connector.py`): Manages connection to Plex server with 3-second timeout, handles library detection, and provides methods to find media items (shows, movies, collections).

**UploadProcessor** (`processors/upload_processor.py`): Core logic for matching scraped artwork to Plex media and uploading. Handles artwork ID tracking via Plex labels to avoid re-uploading unchanged artwork.

**ArtworkProcessor** (`services/artwork_processor.py`): Service layer wrapper that orchestrates scraping and uploading with callback-based progress updates.

**Web Routes** (`web_routes.py`): All Flask HTTP routes and Socket.IO event handlers. The UI communicates via Socket.IO events (e.g., `start_scrape`, `save_bulk_import`, `add_schedule`).

### Data Flow for Artwork Upload

1. User provides URL (via CLI, bulk file, or web UI)
2. `Scraper` detects provider and delegates to specialized scraper
3. Scraper fetches artwork metadata and returns structured lists (`MovieArtworkList`, `TVArtworkList`, `CollectionArtworkList`)
4. `UploadProcessor` matches artwork to Plex media using title/year
5. If `track_artwork_ids` enabled, checks Plex labels to skip unchanged artwork
6. Downloads artwork and uploads to Plex via PlexAPI
7. Updates Plex labels with artwork IDs for future tracking
8. Optionally saves to Kometa asset directory instead of direct upload

### Global State Management

Global state is managed through `core/globals.py`:
- `web_socket`: Flask-SocketIO instance for real-time web updates
- `scheduler_service`: Singleton SchedulerService for scheduled jobs
- `update_service`: Singleton UpdateService for GitHub update checking
- `bulk_file_service`: Singleton BulkFileService for file I/O

Avoid creating new global variables; use dependency injection or extend existing services.

## Configuration

**config.json** is the main configuration file (default location: `config.json` in the working directory):
- `base_url`: Plex server URL (e.g., "http://192.168.1.100:32400")
- `token`: Plex authentication token
- `tv_library`, `movie_library`: Library names (string or array for multiple)
- `track_artwork_ids`: Enable artwork ID tracking via Plex labels (recommended: true)
- `mediux_filters`, `tpdb_filters`: Global artwork type filters (array of filter strings)
- `save_to_kometa`: Save to Kometa asset directory instead of direct Plex upload
- `kometa_base`: Base path to Kometa asset directory
- `reset_overlay`: Remove Kometa overlay label when uploading new artwork

**Custom Config Path**:
- CLI: Use `--config /path/to/custom-config.json` to specify a custom config file location
- Docker: Set `CONFIG_PATH` environment variable (takes precedence over CLI argument)
- The environment variable is useful for Docker deployments where you want to mount config from different locations

**Docker-specific behavior**: When `RUNNING_IN_DOCKER=1` environment variable is set, the app hardcodes Kometa base to `/assets` and temp dir to `/temp`, requiring appropriate volume mappings.

## Kometa Integration

The application supports two Kometa workflows:

1. **Overlay Reset**: Set `reset_overlay: true` to remove the "Overlay" label from Plex items, triggering Kometa to reapply overlays on next run.

2. **Asset Directory**: Set `save_to_kometa: true` to save artwork files to Kometa's asset directory structure instead of uploading to Plex. Requires:
   - `kometa_base` configured
   - Kometa config with `asset_folders: true`, `create_asset_folders: true`, `assets_for_all: true`
   - Directory structure: `<kometa_base>/<Library Name>/<Media Title>/poster.jpg`

## Scrapers

**ThePosterDB** (`scrapers/theposterdb_scraper.py`):
- Rate limited to 6 seconds between requests (`TPDB_RATE_LIMIT_DELAY`)
- Supports sets, user uploads, and individual posters
- `--add-sets` and `--add-posters` options to scrape related content
- Uses BeautifulSoup to parse HTML

**MediUX** (`scrapers/mediux_scraper.py`):
- Supports sets and boxsets (collections of sets)
- Uses MediUX API endpoint: `https://api.mediux.pro/assets/<id>`
- Appends quality suffix: `&w=3840&q=80` for high-res images

Both scrapers return structured artwork lists with metadata (title, year, season, episode, artwork_url, artwork_id).

## Filters and Exclusions

**Filter Types** (defined in `core/constants.py`):
- `show_cover`: TV show poster
- `background`: Background/backdrop image
- `season_cover`: Season poster
- `title_card`: Episode title card
- `movie_poster`: Movie poster
- `collection_poster`: Collection poster

Filters can be set globally in config or per-URL via `--filters` argument.

**Exclusions** (`--exclude`):
- By artwork ID (numeric for ThePosterDB, UUID for MediUX)
- By season/episode: `--exclude s01e05` or `--exclude s02` (entire season)

## Bulk Import Files

Text files in `bulk_imports/` directory with one URL per line:
- Lines starting with `#` or `//` are treated as comments
- Per-line options: `https://mediux.pro/sets/9242 --force --filters show_cover`
- Auto-managed files: Set `auto_manage_bulk_files: true` to auto-sort/label
- Scheduler integration: Each bulk file can have a scheduled run time (format: "HH:MM")

## Web UI and Socket.IO

All web routes and Socket.IO handlers are in `web_routes.py`:

**HTTP Routes**:
- `/`: Main web interface
- `/downloads/<filename>`: Serve processed ZIP files
- `/uploads/<filename>`: Serve uploaded artwork files

**Key Socket.IO Events**:
- `start_scrape`: Initiate scraping from URL
- `start_bulk_import`: Run bulk import file
- `save_bulk_import`, `load_bulk_import`: Manage bulk files
- `load_config`, `save_config`: Configuration management
- `add_schedule`, `delete_schedule`: Job scheduling
- `upload_artwork_chunk`, `upload_complete`: Chunked file uploads

The web UI uses Socket.IO for real-time updates. Services emit events like `status_update`, `log_update`, `progress_update` via callbacks.

## Testing Strategy

**pytest.ini** configures test discovery and markers:
- `@pytest.mark.unit`: Unit tests (no external dependencies)
- `@pytest.mark.integration`: Integration tests (require network)
- `@pytest.mark.slow`: Slow tests (can be excluded with `-m "not slow"`)

**requirements-dev.txt** includes:
- pytest, pytest-cov, pytest-mock for testing
- mypy for type checking
- black, isort, flake8, pylint for code quality

No comprehensive test suite exists yet; contributions welcome.

## Common Development Tasks

### Adding a New Artwork Provider

1. Create scraper class in `scrapers/` inheriting from base patterns
2. Add provider detection logic in `Scraper.__init__()` based on URL
3. Update `Scraper.scrape()` to delegate to new scraper
4. Add provider constants to `core/constants.py`
5. Update README.md with provider documentation

### Adding a New Service

1. Create service class in `services/` directory
2. Export in `services/__init__.py`
3. Initialize singleton in `core/globals.py` if needed
4. Use dependency injection to pass config/dependencies
5. Use `ProcessingCallbacks` for UI updates

### Adding a Socket.IO Event

1. Add handler in `web_routes.py` inside `setup_socket_handlers()`
2. Use `globals.web_socket.emit()` to send responses
3. Update JavaScript in `static/web_interface.js` to handle events
4. Test via web UI

## Important Constraints

**Python Version**: Requires Python 3.10+ due to bug fixes in scraping logic.

**eventlet Compatibility**: eventlet has known issues with Python 3.13; use Python 3.11 or 3.12 for best results.

**Virtual Environment**: Strongly recommended to avoid dependency conflicts, especially on Apple Silicon Macs where architecture mismatches can occur.

**Port Availability**: Default port 4567 must be available; configure via `DEFAULT_WEB_PORT` constant if needed.

**Plex Connection**: 3-second timeout on Plex connections; graceful degradation allows web UI to start even if Plex is unreachable.

## File Organization

- `core/`: Core modules (config, constants, enums, exceptions, globals)
- `models/`: Data models (Options, Instance, artwork types, URL items)
- `scrapers/`: Provider-specific scrapers
- `processors/`: Processing logic (bulk import, upload, metadata)
- `plex/`: Plex-specific modules (connector, uploader)
- `services/`: Service layer for business logic
- `utils/`: Utility functions (notifications, soup utils)
- `static/`: Web UI assets (CSS, JS, images)
- `templates/`: Flask HTML templates
- `bulk_imports/`: User-managed bulk import files

## Version Management

Version is defined in `core/__version__.py` and used throughout:
- `CURRENT_VERSION` constant in `core/constants.py`
- `current_version` variable in `artwork_uploader.py` (for autoupdater)
- Update checking via GitHub API (`UpdateService`)

Use `bump_version.py` script for version bumps.
