# Technical Information for Contributors

This document provides technical details about the Artwork Uploader for Plex architecture, codebase structure, and contribution guidelines for developers.

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Project Structure](#project-structure)
3. [Service Layer](#service-layer)
4. [Web Routes](#web-routes)
5. [Callback Pattern](#callback-pattern)
6. [Testing](#testing)
7. [Contributing](#contributing)
8. [Development Setup](#development-setup)

---

## Architecture Overview

The application follows a layered architecture pattern to separate concerns and improve maintainability:

```
┌─────────────────────────────────────────┐
│         Web Interface (Flask)           │
│  templates/ + static/ + web_routes.py   │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│      Main Application Layer             │
│       artwork_uploader.py               │
│  (UI callbacks, orchestration)          │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│         Service Layer                   │
│  ArtworkProcessor, BulkFileService,     │
│  SchedulerService, AssetIndex,          │
│  RunHistory, WebhookService,            │
│  AuthenticationService, NotifyService,  │
│  UpdateService, ImageService,           │
│  UtilityService                         │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│      External Dependencies              │
│  PlexAPI, requests, PIL, Flask, etc.    │
└─────────────────────────────────────────┘
```

### Design Principles

1. **Separation of Concerns**: Business logic (services) is separate from UI logic (main app and web routes)
2. **Dependency Injection**: Services receive dependencies explicitly rather than using globals
3. **Callback Pattern**: Services use callbacks to communicate with UI without tight coupling
4. **Type Safety**: Comprehensive type hints throughout the codebase
5. **Single Responsibility**: Each service class has a focused, well-defined purpose

---

## Project Structure

```
artwork-uploader-plex/
├── artwork_uploader.py          # Entry point: CLI parsing, orchestration, scrape/bulk/schedule flows (~1200 lines)
├── web_routes.py                # Flask routes and Socket.IO handlers (~1400 lines)
├── logging_config.py            # Rotating file + console logging setup
├── bump_version.py              # Version bump and git tag helper
├── requirements.txt             # Runtime dependencies (pinned)
├── requirements-dev.txt         # Test, lint and type-check dependencies
├── pytest.ini                   # Pytest config (testpaths, pythonpath, markers)
├── Dockerfile                   # Container image, exposes 4567
├── docker-compose.example.yml   # Example compose file
│
├── config/                      # Config directory (config.json, asset_index.db and run_history.json live here at runtime)
│   └── config.json.example      # Annotated config template
│
├── core/                        # Core application modules
│   ├── config.py               # Config class, loads/saves config/config.json
│   ├── constants.py            # Application-wide constants
│   ├── enums.py                # str-Enums: FilterType, MediaType, ScraperSource, RunType, RunTrigger, RunOutcome, ...
│   ├── exceptions.py           # Exception hierarchy under ArtworkUploaderException
│   ├── globals.py              # Module-level shared state (config, web_app, web_socket, plex, scheduler_service)
│   ├── retry.py                # is_transient_error / call_with_retry for uploads and downloads
│   └── __version__.py          # Version metadata
│
├── models/                      # Data models
│   ├── arguments.py            # argparse command-line definition
│   ├── artwork_types.py        # TypedDicts: MovieArtwork, TVArtwork, CollectionArtwork, UploadedFileArtwork
│   ├── bulk_schedule.py        # BulkSchedule: one scheduled bulk import (file, time or interval, next run)
│   ├── callbacks.py            # ProcessingCallbacks: UI callbacks plus the run counters and outcome logic
│   ├── instance.py             # Instance: identifies a CLI or web session
│   ├── options.py              # Options: per-run scrape/upload flags and filters
│   └── url_item.py             # URLItem: a URL with its own Options
│
├── scrapers/                    # Website scrapers
│   ├── scraper.py              # Picks the source from the URL and delegates
│   ├── mediux_scraper.py       # MediUX scraper
│   └── theposterdb_scraper.py  # ThePosterDB scraper, including user crawls and the asset index
│
├── processors/                  # Processing logic
│   ├── upload_processor.py     # UploadProcessor: resolves media in Plex and drives the upload
│   └── media_metadata.py       # parse_show / parse_movie / parse_title title-and-year parsing
│
├── plex/                        # Plex-specific modules
│   ├── plex_connector.py       # PlexConnector: connection, library sections, media lookup
│   ├── plex_uploader.py        # PlexUploader: posts artwork, label handling, retry
│   └── library_index.py        # PlexLibraryIndex: cached normalised title index of the libraries
│
├── services/                    # Service layer (11 modules, ~2000 lines)
│   ├── __init__.py             # Service exports
│   ├── artwork_processor.py    # Coordinates scrape then upload
│   ├── asset_index.py          # SQLite index of a ThePosterDB user's uploads
│   ├── authentication_service.py # bcrypt hashing and login check for the web UI
│   ├── bulk_file_service.py    # Bulk import file I/O
│   ├── image_service.py        # Image orientation and dimensions
│   ├── notify_service.py       # Thin Apprise wrapper
│   ├── run_history.py          # JSON record of every run, with pruning
│   ├── scheduler_service.py    # Scheduled bulk imports, catch-up, single-flight guard
│   ├── update_service.py       # GitHub release check
│   ├── utility_service.py      # Exe dir and artwork sort key
│   └── webhook_service.py      # Radarr/Sonarr import webhook with retry queue
│
├── kometa/
│   └── kometa_saver.py         # Writes artwork to a Kometa assets folder instead of Plex
│
├── utils/                       # Utility modules
│   ├── utils.py                # URL parsing, bulk file parsing, md5, elapsed time
│   ├── soup_utils.py           # BeautifulSoup fetch/parse helper
│   └── notifications.py        # update_log / debug_me / status plumbing and Apprise dispatch
│
├── tests/                       # Pytest suite (26 files, 200+ tests), run with `pytest` from the repo root
├── static/                      # Web UI assets (CSS, JS, favicons)
├── templates/                   # Flask HTML templates (web_interface.html, login.html)
├── assets/                      # README screenshots
├── .github/workflows/           # Release workflow
├── bulk_imports/                # Bulk import text files (created at runtime)
└── .venv/                       # Virtual environment (not in git)
```

### Key Metrics

- **Main file**: ~1200 lines (artwork_uploader.py)
- **Web layer**: ~1400 lines (web_routes.py)
- **Service layer**: ~2000 lines across 11 modules
- **Flask surface**: 8 HTTP routes + 27 Socket.IO handlers
- **Tests**: 26 files, 200+ test functions

---

## Service Layer

The service layer encapsulates all business logic with clear, testable interfaces.

### BulkFileService

**Purpose**: Centralized bulk import file I/O operations

**Location**: [services/bulk_file_service.py](services/bulk_file_service.py)

**Key Methods**:
```python
class BulkFileService:
    def __init__(self, base_dir: str)

    def get_bulk_file_path(self, filename: Optional[str] = None) -> str
    def file_exists(self, filename: Optional[str] = None) -> bool
    def read_file(self, filename: Optional[str] = None) -> str
    def write_file(self, contents: str, filename: Optional[str] = None) -> None
    def rename_file(self, old_name: str, new_name: str) -> None
    def delete_file(self, filename: str) -> None
    def ensure_default_file_exists(self, filename: Optional[str] = None) -> None
```

**Usage Example**:
```python
from services import BulkFileService

# Initialize service
bulk_service = BulkFileService(base_dir="/path/to/project")

# Read bulk import file
if bulk_service.file_exists("bulk_import.txt"):
    contents = bulk_service.read_file("bulk_import.txt")

# Write updated contents
bulk_service.write_file(updated_contents, "bulk_import.txt")
```

---

### ImageService

**Purpose**: Image processing utilities (orientation detection, dimensions)

**Location**: [services/image_service.py](services/image_service.py)

**Key Methods**:
```python
class ImageService:
    @staticmethod
    def check_orientation(image_path: str) -> Literal["landscape", "portrait", "square"]

    @staticmethod
    def get_dimensions(image_path: str) -> tuple[int, int]
```

**Usage Example**:
```python
from services import ImageService

# Check image orientation
orientation = ImageService.check_orientation("/path/to/image.jpg")
if orientation == "landscape":
    print("Image is landscape")

# Get dimensions
width, height = ImageService.get_dimensions("/path/to/image.jpg")
```

---

### ArtworkProcessor

**Purpose**: Core business logic for scraping and uploading artwork to Plex

**Location**: [services/artwork_processor.py](services/artwork_processor.py)

**Key Methods**:
```python
class ArtworkProcessor:
    def __init__(self, plex: PlexConnector, callbacks: Optional[ProcessingCallbacks]) -> None

    def scrape_and_process(
        self,
        url: str,
        bulk: bool,
        options: Options
    ) -> Tuple[Optional[str], Optional[str]]

    def process_uploaded_files(
        self,
        file_list: list[dict],
        skipped: int,
        zip_title: Optional[str],
        zip_author: Optional[str],
        zip_source: Optional[str],
        options: Options,
        override_title: Optional[str] = None
    ) -> None
```

The callbacks are given to the constructor, not to the individual calls, and the processor takes the app's own `PlexConnector` rather than a raw plexapi `PlexServer`. `ProcessingCallbacks` lives in [models/callbacks.py](models/callbacks.py); see [Callback Pattern](#callback-pattern).

**Usage Example**:
```python
from services.artwork_processor import ArtworkProcessor
from models.callbacks import ProcessingCallbacks
from plex.plex_connector import PlexConnector

callbacks = ProcessingCallbacks(
    on_status_update=my_status_callback,
    on_log_update=my_log_callback,
)

plex = PlexConnector(base_url, token)
processor = ArtworkProcessor(plex, callbacks)

# Process artwork from URL. Returns (result, artwork_title).
result, title = processor.scrape_and_process(
    url="https://mediux.pro/sets/9242",
    bulk=False,
    options=options,
)
```

---

### SchedulerService

**Purpose**: Manage scheduled bulk imports: daily and interval schedules, missed-run catch-up, and the single-flight guard that stops two runs of the same file overlapping

**Location**: [services/scheduler_service.py](services/scheduler_service.py)

**Key Methods**:
```python
class SchedulerService:
    def __init__(self, check_interval: int = 1)

    def add_schedule(self, sched: BulkSchedule, callback: Callable[[str], None]) -> str
    def remove_schedule(self, job_id: str) -> bool
    def rename_file(self, old_name: str, new_name: str) -> None
    def clear_all_schedules(self) -> None
    def get_jobs_for_file(self, filename: str) -> List[str]
    def get_all_job_ids(self) -> List[str]
    def has_schedules(self) -> bool
    def start(self) -> bool
    def stop(self) -> None

    # Single-flight guard: a run calls try_start first and finish when done.
    def try_start(self, filename: str) -> bool
    def finish(self, filename: str) -> None

    @staticmethod
    def get_missed_run(sched: BulkSchedule, window_minutes: int) -> Optional[str]
```

A schedule is described by a `BulkSchedule` ([models/bulk_schedule.py](models/bulk_schedule.py)): the bulk file it runs, either a daily `time` ("HH:MM") or an `interval_value`/`interval_unit` pair, and its computed `next_run`.

**Usage Example**:
```python
from services import SchedulerService
from models.bulk_schedule import BulkSchedule

scheduler = SchedulerService(check_interval=1)

def run_bulk_import(filename):
    print(f"Running bulk import for {filename}")

sched = BulkSchedule(file="bulk_import_movies.txt", time="05:30")
job_id = scheduler.add_schedule(sched, callback=run_bulk_import)

scheduler.start()

# Later, remove the schedule
scheduler.remove_schedule(job_id)
```

---

### AssetIndex

**Purpose**: A SQLite index (in the config directory) of a ThePosterDB user's uploads, so a repeat scrape only fetches pages until it reaches assets it has already seen, and other features can look cached artwork up by title

**Location**: [services/asset_index.py](services/asset_index.py)

Module functions `normalize_title`, `page_is_fully_known` and `full_crawl_due` support the scraper's crawl decisions. The index is what makes `cache_user_scrapes` and the Sonarr/Radarr webhook work.

---

### RunHistory

**Purpose**: A JSON record (in the config directory) of every run, whatever started it: a manual bulk run, a schedule, a single URL scrape, a ZIP upload, or a webhook apply. Pruned by count and age. Writes are serialized per file path so two runs finishing at once cannot clobber each other

**Location**: [services/run_history.py](services/run_history.py)

```python
class RunHistory:
    def add_run(self, run_type, label, started_at, ended_at, trigger, outcome,
                assets_processed=0, success_count=0, cached_count=0,
                locked_count=0, error_count=0) -> None
    def get_runs(self) -> List[Dict[str, Any]]
```

The History tab in the web UI reads this file. `RunType`, `RunTrigger` and `RunOutcome` in [core/enums.py](core/enums.py) define the vocabulary.

---

### WebhookService

**Purpose**: Handles Radarr/Sonarr "Download" import events: looks the imported title up in the asset index and applies the cached poster through the normal upload path, retrying on a delay schedule while Plex finishes scanning the new file

**Location**: [services/webhook_service.py](services/webhook_service.py)

`parse_event` turns the incoming JSON into a `WebhookEvent`; the service dedupes concurrent events per title and records each apply in the run history.

---

### AuthenticationService

**Purpose**: bcrypt password hashing and login verification for the web UI's optional password protection

**Location**: [services/authentication_service.py](services/authentication_service.py)

```python
class AuthenticationService:
    @staticmethod
    def hash_password(password: str) -> str
    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool
    @staticmethod
    def authenticate(username: str, password: str) -> bool
```

---

### NotifyService

**Purpose**: Thin wrapper over [Apprise](https://github.com/caronc/apprise) for push notifications

**Location**: [services/notify_service.py](services/notify_service.py)

`add_url`, `clear_urls` and `send_notification`. Which events notify which channel is decided in [utils/notifications.py](utils/notifications.py) from the per-channel event selection in the config.

---

### UpdateService

**Purpose**: Check for updates from GitHub releases

**Location**: [services/update_service.py](services/update_service.py)

**Key Methods**:
```python
class UpdateService:
    def __init__(
        self,
        github_repo: str,
        current_version: str,
        check_interval: int = 3600
    )

    def get_latest_version(self) -> Optional[str]
    def check_for_update(self) -> Optional[str]

    def start_periodic_check(
        self,
        on_update_available: Callable[[str], None]
    ) -> bool

    def stop_periodic_check(self) -> None
```

**Usage Example**:
```python
from services.update_service import UpdateService
from core.constants import GITHUB_REPO
from core.__version__ import __version__

update_service = UpdateService(
    github_repo=GITHUB_REPO,
    current_version=__version__,
    check_interval=3600  # Check every hour
)

# Check once
latest = update_service.check_for_update()
if latest:
    print(f"Update available: {latest}")

# Or start periodic checking
def on_update(version):
    print(f"New version available: {version}")

update_service.start_periodic_check(on_update_available=on_update)
```

---

### UtilityService

**Purpose**: General utility functions (paths, sorting)

**Location**: [services/utility_service.py](services/utility_service.py)

**Key Methods**:
```python
class UtilityService:
    @staticmethod
    def get_exe_dir() -> str
    """Get project root directory (works with frozen executables)"""

    @staticmethod
    def sort_key(item: dict) -> Tuple[str, str, float, float, str]
    """Complex sorting logic for artwork items"""
```

**Usage Example**:
```python
from services import UtilityService

# Get project root directory
project_root = UtilityService.get_exe_dir()

# Sort artwork items
artwork_list = [
    {"media": "Movie", "artwork_url": "...", ...},
    {"media": "Show", "season": 1, "episode": 5, ...}
]
sorted_artwork = sorted(artwork_list, key=UtilityService.sort_key)
```

**A note on imports**: `services/__init__.py` exports most services, but not all of them. `ArtworkProcessor` and `UpdateService` are imported by full path (`from services.artwork_processor import ArtworkProcessor`), and `ProcessingCallbacks` lives in `models.callbacks`, not in `services`. When in doubt, import by full module path.

---

## Web Routes

All Flask HTTP routes and Socket.IO event handlers are in [web_routes.py](web_routes.py).

### HTTP Routes

```python
def setup_routes(web_app, config: Config):
    @web_app.route("/")
    @login_required
    def home():
        """Main web interface"""

    @web_app.route("/login", methods=["GET", "POST"])
    def login():
        """Login form, when password protection is enabled"""

    @web_app.route("/logout")
    def logout():
        """End the session"""

    @web_app.route("/api/browse", methods=["GET"])
    def browse():
        """Directory listing for the folder-picker in Settings"""

    @web_app.route('/downloads/<path:filename>')
    @login_required
    def download_file(filename):
        """Download processed ZIP files"""

    @web_app.route('/uploads/<path:filename>')
    @login_required
    def uploaded_file(filename):
        """Serve uploaded artwork files"""

    @web_app.route("/webhook/radarr", methods=["POST"])
    @web_app.route("/webhook/sonarr", methods=["POST"])
    def webhook(source):
        """Sonarr/Radarr import webhook (404 unless enable_webhooks is on)"""
```

The main pages sit behind `@login_required`, which is a pass-through unless password protection is enabled in Settings. The webhook routes authenticate with the webhook token instead of the session.

### Socket.IO Event Handlers

The application uses Socket.IO for real-time communication with the web UI. All 27 handlers are defined in `setup_socket_handlers()`:

```python
def setup_socket_handlers(config: Config, filename_pattern: re.Pattern):
    # Update checking
    @globals.web_socket.on("check_for_update")
    @globals.web_socket.on("update_app")

    # Artwork processing
    @globals.web_socket.on("start_scrape")
    @globals.web_socket.on("start_bulk_import")
    @globals.web_socket.on("stop_scrape")
    @globals.web_socket.on("get_scrape_state")

    # Bulk file management
    @globals.web_socket.on("save_bulk_import")
    @globals.web_socket.on("load_bulk_filelist")
    @globals.web_socket.on("load_bulk_import")
    @globals.web_socket.on("rename_bulk_file")
    @globals.web_socket.on("delete_bulk_file")
    @globals.web_socket.on("create_bulk_file")

    # Configuration
    @globals.web_socket.on("load_config")
    @globals.web_socket.on("save_config")
    @globals.web_socket.on("get_plex_libraries")
    @globals.web_socket.on("test_notifications")
    @globals.web_socket.on("create_directory")
    @globals.web_socket.on("detect_docker")

    # Scheduling
    @globals.web_socket.on("add_schedule")
    @globals.web_socket.on("delete_schedule")
    @globals.web_socket.on("get_schedules")

    # Run history
    @globals.web_socket.on("load_run_history")

    # File uploads (chunked)
    @globals.web_socket.on("upload_artwork_chunk")
    @globals.web_socket.on("upload_complete")

    # UI updates and session
    @globals.web_socket.on("display_message")
    @globals.web_socket.on("debug_mode")
    @globals.web_socket.on("disconnect")
```

Scheduling state lives in `globals.scheduler_service`; the handlers no longer carry job dictionaries around.

### Adding New Routes

To add a new HTTP route:

1. Add the route function in `web_routes.py` inside `setup_routes()`:
```python
def setup_routes(web_app, config: Config):
    # ... existing routes ...

    @web_app.route('/my-new-route')
    def my_new_route():
        return jsonify({"status": "success"})
```

To add a new Socket.IO handler:

1. Add the handler in `web_routes.py` inside `setup_socket_handlers()`:
```python
def setup_socket_handlers(config, filename_pattern):
    # ... existing handlers ...

    @globals.web_socket.on("my_new_event")
    def handle_my_event(data):
        # Process data
        globals.web_socket.emit("response_event", {"result": "..."})
```

---

## Callback Pattern

The application uses a callback pattern to separate business logic from UI updates.

### Why Callbacks?

1. **Decoupling**: Services don't need to know about UI implementation
2. **Testability**: Services can be tested without UI dependencies
3. **Flexibility**: Different UIs (CLI, web, API) can use the same services

### ProcessingCallbacks

**Location**: [models/callbacks.py](models/callbacks.py)

```python
@dataclass
class ProcessingCallbacks:
    """Callbacks for UI updates during artwork processing, plus the run counters."""

    on_status_update: Optional[Callable[[str, str, bool, bool], None]] = None
    # Args: message, color, spinner, sticky

    on_log_update: Optional[Callable[[str], None]] = None
    # Args: message

    on_progress_update: Optional[Callable[[int, int, str, str, str], None]] = None
    # Args: current, total, title, bar_type, bar_speed

    on_debug: Optional[Callable[[str, Optional[str]], None]] = None
    # Args: message, context

    # Run counters, shared with the caller as single-element lists
    success_counter: list = field(default_factory=lambda: [0])
    assets_processed: list = field(default_factory=lambda: [0])
    cached_counter: list = field(default_factory=lambda: [0])
    locked_counter: list = field(default_factory=lambda: [0])
    failed_counter: list = field(default_factory=lambda: [0])
```

It is more than a data holder: helper methods `status()`, `log()`, `debug()` and `progress()` call the callbacks and guard against `None` internally, `success()` / `assets()` / `cached()` / `locked()` / `failed()` / `record_result()` bump the counters, and `outcome()` is the single place a run's result (success, partial, failed, skipped, stopped) is decided from those counters. Run outcomes shown in the History tab all come from `outcome()`.

### Using Callbacks in Services

Inside a service method, call the helpers rather than the raw callback fields:

```python
def process_something(self, data):
    self.callbacks.status("Processing started", "primary")

    for i, item in enumerate(data):
        self.callbacks.progress(i + 1, len(data), item.title, "scrape", "normal")
        # Process item...

    self.callbacks.log("Processing completed")
```

### Implementing Callbacks in UI

In the main application or web routes:

```python
from models.callbacks import ProcessingCallbacks

def my_status_callback(message, color, spinner, sticky):
    # Update web UI via Socket.IO
    globals.web_socket.emit("status_update", {
        "message": message,
        "color": color,
        "spinner": spinner,
        "sticky": sticky
    })

def my_log_callback(message):
    # Append to log file or send to UI
    print(f"[LOG] {message}")

callbacks = ProcessingCallbacks(
    on_status_update=my_status_callback,
    on_log_update=my_log_callback
)

processor = ArtworkProcessor(plex, callbacks)
result, title = processor.scrape_and_process(url, bulk=False, options=options)
```

---

## Testing

### Running the Test Suite

The repo carries a pytest suite: 26 files and over 200 tests under [tests/](tests/).

```bash
# Install the dev dependencies (pytest, pytest-cov, pytest-mock, pytest-asyncio, plus lint and type-check tools)
pip install -r requirements-dev.txt

# Run the suite from the repo root (pytest.ini sets testpaths and pythonpath, so the root matters)
pytest
```

Three markers are registered in `pytest.ini`: `slow`, `integration` and `unit`. Tests are plain pytest functions; new tests should follow that style rather than `unittest.TestCase`.

Run the suite before and after your change. A failure on an untouched checkout is worth reporting on its own.

### Manual Testing

The application should also be exercised by hand after any change that touches the UI or the Plex path.

#### Basic Startup Test

```bash
# Activate virtual environment
source .venv/bin/activate  # macOS/Linux
# or
.venv\Scripts\activate     # Windows

# Start the application
python artwork_uploader.py

# Verify web UI loads at http://localhost:4567
```

#### Port Check Test

```bash
# Start in background
.venv/bin/python artwork_uploader.py &

# Wait a few seconds
sleep 3

# Check if port is listening
lsof -ti:4567  # Should return a process ID
```

#### Route Test

```bash
# Test home route
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:4567/

# HTTP 200, or a redirect to /login when password protection is enabled
```

### Testing After Refactoring

When refactoring code:

1. **Run the suite after each logical change** - Don't stack multiple changes before testing
2. **Verify web UI loads** - Check http://localhost:4567
3. **Check for Python errors** - Review console output for tracebacks
4. **Test key features**:
   - Load bulk import files
   - Save configuration
   - Start a scrape operation
   - Check scheduled jobs

---

## Contributing

We welcome contributions! Here's how to get started:

### Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/artwork-uploader-plex.git
   cd artwork-uploader-plex
   ```
3. **Create a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # macOS/Linux
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```
4. **Create a branch** for your feature:
   ```bash
   git checkout -b feature/my-new-feature
   ```

### Contribution Guidelines

1. **Follow the existing code style**:
   - Use type hints for all function parameters and return values
   - Add docstrings to classes and methods
   - Keep functions focused on a single responsibility
   - Use meaningful variable names

2. **Test your changes**:
   - Run `pytest` and keep it green
   - Test the specific feature you added/modified
   - Check that existing features still work

3. **Keep commits focused**:
   - One logical change per commit
   - Write clear commit messages
   - Example: "Add support for custom artwork filters in bulk files"

4. **Update documentation**:
   - Update README.md if you add user-facing features
   - Update TECHNICAL_INFO.md if you change architecture
   - Add code comments for complex logic

5. **Submit a pull request**:
   - Describe what your PR does
   - Reference any related issues
   - Be responsive to code review feedback

### Code Style Examples

**Good**:
```python
def process_artwork_items(
    items: list[dict],
    filter_type: str,
    callbacks: Optional[ProcessingCallbacks] = None
) -> int:
    """Process a list of artwork items with optional filtering.

    Args:
        items: List of artwork dictionaries
        filter_type: Type of filter to apply (e.g., 'movie_poster')
        callbacks: Optional callbacks for UI updates

    Returns:
        Number of items successfully processed
    """
    processed_count = 0

    for item in items:
        if item.get("type") == filter_type:
            if callbacks:
                callbacks.progress(processed_count + 1, len(items), item.get("title", ""), "scrape", "normal")

            # Process item...
            processed_count += 1

    return processed_count
```

**Bad**:
```python
def process(items, type, cbs=None):  # No type hints
    c = 0  # Unclear variable name
    for i in items:
        if i["type"] == type:  # No .get(), will crash if key missing
            # Do stuff...  # Vague comment
            c += 1
    return c
```

### Areas for Contribution

Here are some areas where contributions would be particularly valuable:

1. **Testing**:
   - Widen coverage of the scrapers and the upload path
   - Add integration tests against a mock Plex server

2. **Features**:
   - Add support for new artwork providers
   - Improve error handling and recovery
   - Add more configuration options

3. **Documentation**:
   - Improve code comments
   - Add more usage examples
   - Create video tutorials

4. **Performance**:
   - Optimize image processing
   - Reduce memory usage for large bulk imports
   - Speed up scraping operations

5. **UI/UX**:
   - Improve web interface design
   - Better error messages for users

---

## Development Setup

### Prerequisites

- Python 3.12 or later (the app refuses to start on anything older)
- pip (Python package installer)
- Git

### Initial Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/mscodemonkey/artwork-uploader-plex.git
   cd artwork-uploader-plex
   ```

2. **Create virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # macOS/Linux
   # or
   .venv\Scripts\activate     # Windows
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

4. **Configure the application**:
   ```bash
   cp config/config.json.example config/config.json
   # Edit config/config.json with your Plex server details
   # (or skip this: the app creates one on first run and you can configure it in the web UI)
   ```

5. **Run the application**:
   ```bash
   python artwork_uploader.py
   ```

6. **Access the web UI**:
   - Open browser to http://localhost:4567

### Development Tools

The dev tooling is pinned in `requirements-dev.txt`:

- **Tests**: pytest, pytest-cov, pytest-mock, pytest-asyncio
- **Linter**: pylint or flake8 for code quality
- **Formatter**: black for consistent code formatting
- **Type Checker**: mypy for static type checking

### Common Development Tasks

#### Adding a New Service

1. Create new file in `services/` directory:
   ```python
   # services/my_new_service.py
   from typing import Optional

   class MyNewService:
       def __init__(self, config: dict):
           self.config = config

       def do_something(self, param: str) -> bool:
           """Do something useful."""
           # Implementation...
           return True
   ```

2. Export in `services/__init__.py` (or import it by full path, which several existing services do):
   ```python
   from .my_new_service import MyNewService

   __all__ = [
       # ... existing exports ...
       'MyNewService'
   ]
   ```

3. Use in `artwork_uploader.py`:
   ```python
   from services import MyNewService

   # Initialize
   my_service = MyNewService(config)

   # Use
   result = my_service.do_something("parameter")
   ```

4. Add a test file in `tests/` covering its behaviour.

#### Adding a New Socket.IO Handler

1. Edit `web_routes.py` in `setup_socket_handlers()`:
   ```python
   @globals.web_socket.on("my_new_event")
   def handle_my_new_event(data):
       """Handle my new event."""
       # Process data...
       result = do_something(data)

       # Send response
       globals.web_socket.emit("my_response_event", {
           "result": result,
           "status": "success"
       })
   ```

2. Add JavaScript in `templates/web_interface.html` or `static/web_interface.js`:
   ```javascript
   // Send event
   socket.emit("my_new_event", {param: "value"});

   // Listen for response
   socket.on("my_response_event", function(data) {
       console.log("Got result:", data.result);
   });
   ```

---

## Troubleshooting Development Issues

### Import Errors

**Issue**: `ModuleNotFoundError: No module named 'plexapi'`

**Solution**: Ensure virtual environment is activated and dependencies installed:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Port Already in Use

**Issue**: `OSError: [Errno 48] Address already in use`

**Solution**: Kill existing process:
```bash
lsof -ti:4567 | xargs kill -9
```

### Type Hint Errors

**Issue**: Type checker complains about missing types

**Solution**: Add proper type hints:
```python
# Before
def my_function(param):
    return param

# After
def my_function(param: str) -> str:
    return param
```

---

## Questions or Issues?

- **GitHub Issues**: https://github.com/mscodemonkey/artwork-uploader-plex/issues
- **Discussions**: Use GitHub Discussions for questions and ideas
- **Pull Requests**: Submit PRs for bug fixes and features

Thank you for contributing to Artwork Uploader for Plex!
