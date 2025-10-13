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
│  BulkFileService, ImageService,         │
│  ArtworkProcessor, SchedulerService,    │
│  UpdateService, UtilityService          │
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
plex-poster-set-helper/
├── artwork_uploader.py          # Main application entry point (724 lines)
├── web_routes.py                # Flask routes and Socket.IO handlers (568 lines)
├── logging_config.py            # Logging configuration
├── config.json                  # User configuration
├── requirements.txt             # Python dependencies
│
├── core/                        # Core application modules
│   ├── config.py               # Application configuration
│   ├── constants.py            # Application constants
│   ├── enums.py                # Enumerations
│   ├── exceptions.py           # Custom exceptions
│   ├── globals.py              # Global state
│   └── __version__.py          # Version information
│
├── models/                      # Data models
│   ├── instance.py             # Instance/scraper classes
│   ├── options.py              # Configuration and options
│   ├── arguments.py            # Command-line arguments
│   ├── artwork_types.py        # Artwork type definitions
│   └── url_item.py             # URL item model
│
├── scrapers/                    # Website scrapers
│   ├── scraper.py              # Base scraper class
│   ├── mediux_scraper.py       # MediUX scraper
│   └── theposterdb_scraper.py  # ThePosterDB scraper
│
├── processors/                  # Processing logic
│   ├── bulk_import.py          # Bulk import processing
│   ├── upload_processor.py     # Upload processing logic
│   └── media_metadata.py       # Media metadata handling
│
├── plex/                        # Plex-specific modules
│   ├── plex_connector.py       # Plex server connection
│   └── plex_uploader.py        # Plex artwork uploader
│
├── utils/                       # Utility modules
│   ├── utils.py                # General utilities
│   ├── soup_utils.py           # BeautifulSoup utilities
│   └── notifications.py        # Notification handling
│
├── services/                    # Service layer (831 lines total)
│   ├── __init__.py             # Service exports
│   ├── artwork_processor.py    # Core artwork processing logic (274 lines)
│   ├── bulk_file_service.py    # Bulk file I/O operations (148 lines)
│   ├── image_service.py        # Image utilities (56 lines)
│   ├── scheduler_service.py    # Job scheduling (158 lines)
│   ├── update_service.py       # GitHub update checking (110 lines)
│   └── utility_service.py      # General utilities (62 lines)
│
├── static/                      # Web UI assets (CSS, JS, images)
├── templates/                   # Flask HTML templates
├── bulk_imports/                # Bulk import text files
└── .venv/                       # Virtual environment (not in git)
```

### Key Metrics

- **Total codebase reduction**: 40% (1206 → 724 lines in main file)
- **Service layer**: 831 lines across 7 modules
- **Type hint coverage**: ~90%
- **Number of Flask routes**: 3 HTTP routes + 17 Socket.IO handlers

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

**Key Classes**:
```python
@dataclass
class ProcessingCallbacks:
    """Callbacks for UI updates during artwork processing."""
    on_status_update: Optional[Callable[[str, str, bool, bool], None]] = None
    on_log_update: Optional[Callable[[str], None]] = None
    on_progress_update: Optional[Callable[[int, int], None]] = None
    on_debug: Optional[Callable[[str, str], None]] = None

class ArtworkProcessor:
    def __init__(self, plex: PlexServer)

    def scrape_and_process(
        self,
        url: str,
        options: Options,
        callbacks: Optional[ProcessingCallbacks] = None
    ) -> Optional[str]

    def process_uploaded_files(
        self,
        file_list: list[dict],
        options: Options,
        callbacks: Optional[ProcessingCallbacks] = None,
        override_title: Optional[str] = None
    ) -> None
```

**Usage Example**:
```python
from services import ArtworkProcessor, ProcessingCallbacks
from plexapi.server import PlexServer

# Define callbacks for UI updates
def on_status(msg, color, temp, important):
    print(f"[{color}] {msg}")

def on_log(msg):
    print(f"LOG: {msg}")

callbacks = ProcessingCallbacks(
    on_status_update=on_status,
    on_log_update=on_log
)

# Initialize processor
plex = PlexServer(base_url, token)
processor = ArtworkProcessor(plex)

# Process artwork from URL
result = processor.scrape_and_process(
    url="https://mediux.pro/sets/9242",
    options=options,
    callbacks=callbacks
)
```

---

### SchedulerService

**Purpose**: Manage scheduled jobs for bulk imports

**Location**: [services/scheduler_service.py](services/scheduler_service.py)

**Key Methods**:
```python
class SchedulerService:
    def __init__(self, check_interval: int = 1)

    def add_schedule(
        self,
        filename: str,
        schedule_time: str,  # Format: "HH:MM"
        callback: Callable[[str], None]
    ) -> str  # Returns job_id

    def remove_schedule(self, job_id: str) -> bool
    def start(self) -> bool
    def stop(self) -> None
    def has_schedules(self) -> bool
    def get_schedule_for_file(self, filename: str) -> Optional[str]
```

**Usage Example**:
```python
from services import SchedulerService

# Initialize scheduler
scheduler = SchedulerService(check_interval=1)

# Add a scheduled job
def run_bulk_import(filename):
    print(f"Running bulk import for {filename}")

job_id = scheduler.add_schedule(
    filename="bulk_import_movies.txt",
    schedule_time="05:30",
    callback=run_bulk_import
)

# Start the scheduler
scheduler.start()

# Later, remove the schedule
scheduler.remove_schedule(job_id)
```

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
from services import UpdateService

# Initialize update service
update_service = UpdateService(
    github_repo="martinjsteven/plex-poster-set-helper",
    current_version="0.3.0",
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
    def sort_key(item: dict) -> Tuple[str, float, float, str]
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

---

## Web Routes

All Flask HTTP routes and Socket.IO event handlers are in [web_routes.py](web_routes.py).

### HTTP Routes

```python
def setup_routes(web_app, config: Config):
    @web_app.route("/")
    def home():
        """Main web interface"""

    @web_app.route('/downloads/<path:filename>')
    def download_file(filename):
        """Download processed ZIP files"""

    @web_app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        """Serve uploaded artwork files"""
```

### Socket.IO Event Handlers

The application uses Socket.IO for real-time communication with the web UI. All handlers are defined in `setup_socket_handlers()`:

```python
def setup_socket_handlers(config, scheduled_jobs, scheduled_jobs_by_file, filename_pattern):
    # Update checking
    @globals.web_socket.on("check_for_update")
    @globals.web_socket.on("update_app")

    # Artwork processing
    @globals.web_socket.on("start_scrape")
    @globals.web_socket.on("start_bulk_import")

    # Bulk file management
    @globals.web_socket.on("save_bulk_import")
    @globals.web_socket.on("load_bulk_filelist")
    @globals.web_socket.on("load_bulk_import")
    @globals.web_socket.on("rename_bulk_file")
    @globals.web_socket.on("delete_bulk_file")

    # Configuration
    @globals.web_socket.on("load_config")
    @globals.web_socket.on("save_config")

    # Scheduling
    @globals.web_socket.on("add_schedule")
    @globals.web_socket.on("delete_schedule")

    # File uploads (chunked)
    @globals.web_socket.on("upload_artwork_chunk")
    @globals.web_socket.on("upload_complete")

    # UI updates
    @globals.web_socket.on("display_message")
```

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
def setup_socket_handlers(config, ...):
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

### ProcessingCallbacks Dataclass

```python
@dataclass
class ProcessingCallbacks:
    """Callbacks for UI updates during artwork processing.

    All callbacks are optional. If None, no update is sent.
    """
    on_status_update: Optional[Callable[[str, str, bool, bool], None]] = None
    # Args: message, color, temp, important

    on_log_update: Optional[Callable[[str], None]] = None
    # Args: message

    on_progress_update: Optional[Callable[[int, int], None]] = None
    # Args: current, total

    on_debug: Optional[Callable[[str, str], None]] = None
    # Args: title, message
```

### Using Callbacks in Services

Inside a service method:

```python
def process_something(self, data, callbacks: Optional[ProcessingCallbacks] = None):
    # Notify UI of status change
    if callbacks and callbacks.on_status_update:
        callbacks.on_status_update("Processing started", "primary", False, False)

    # Do work...
    for i, item in enumerate(data):
        # Update progress
        if callbacks and callbacks.on_progress_update:
            callbacks.on_progress_update(i + 1, len(data))

        # Process item...

    # Log completion
    if callbacks and callbacks.on_log_update:
        callbacks.on_log_update("Processing completed")
```

### Implementing Callbacks in UI

In the main application or web routes:

```python
from services import ProcessingCallbacks

def my_status_callback(message, color, temp, important):
    # Update web UI via Socket.IO
    globals.web_socket.emit("status_update", {
        "message": message,
        "color": color,
        "temp": temp,
        "important": important
    })

def my_log_callback(message):
    # Append to log file or send to UI
    print(f"[LOG] {message}")

callbacks = ProcessingCallbacks(
    on_status_update=my_status_callback,
    on_log_update=my_log_callback
)

# Use with service
processor.scrape_and_process(url, options, callbacks)
```

---

## Testing

### Manual Testing

The application should be tested after any changes to ensure functionality is preserved.

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

# Should output: HTTP 200
```

### Testing After Refactoring

When refactoring code:

1. **Test after each logical change** - Don't make multiple changes before testing
2. **Verify web UI loads** - Check http://localhost:4567
3. **Check for Python errors** - Review console output for tracebacks
4. **Test key features**:
   - Load bulk import files
   - Save configuration
   - Start a scrape operation
   - Check scheduled jobs

### Unit Testing (Future)

The service layer is designed to be easily unit-testable. Future contributions should include unit tests for service methods.

Example test structure:

```python
import unittest
from services import ImageService

class TestImageService(unittest.TestCase):
    def test_check_orientation_landscape(self):
        # Create test image
        orientation = ImageService.check_orientation("test_landscape.jpg")
        self.assertEqual(orientation, "landscape")

    def test_check_orientation_portrait(self):
        orientation = ImageService.check_orientation("test_portrait.jpg")
        self.assertEqual(orientation, "portrait")
```

---

## Contributing

We welcome contributions! Here's how to get started:

### Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/plex-poster-set-helper.git
   cd plex-poster-set-helper
   ```
3. **Create a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # macOS/Linux
   pip install -r requirements.txt
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
   - Run the application and verify it starts correctly
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
            if callbacks and callbacks.on_progress_update:
                callbacks.on_progress_update(processed_count + 1, len(items))

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
   - Add unit tests for service layer
   - Add integration tests for scrapers
   - Create automated test suite

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
   - Add dark/light theme toggle
   - Better error messages for users

---

## Development Setup

### Prerequisites

- Python 3.10 or later
- pip (Python package installer)
- Git

### Initial Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/martinjsteven/plex-poster-set-helper.git
   cd plex-poster-set-helper
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
   ```

4. **Configure the application**:
   ```bash
   cp example_config.json config.json
   # Edit config.json with your Plex server details
   ```

5. **Run the application**:
   ```bash
   python artwork_uploader.py
   ```

6. **Access the web UI**:
   - Open browser to http://localhost:4567

### Development Tools

Recommended tools for development:

- **IDE**: PyCharm, VS Code, or any Python IDE
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

2. Export in `services/__init__.py`:
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

- **GitHub Issues**: https://github.com/martinjsteven/plex-poster-set-helper/issues
- **Discussions**: Use GitHub Discussions for questions and ideas
- **Pull Requests**: Submit PRs for bug fixes and features

Thank you for contributing to Artwork Uploader for Plex!
