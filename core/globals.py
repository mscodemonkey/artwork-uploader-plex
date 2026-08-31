import threading
from typing import Literal
# Application globals
config = None  # Config object
web_app = None  # Flask app
web_socket = None  # SocketIO instance
debug = False  # Debug mode
plex = None  # Plex connector
docker: bool = False # Running in Docker

# Services (initialized in main)
bulk_file_service = None
scheduler_service = None
update_service = None
webhook_service = None

# Scrape cancellation (user-initiated "Stop" from the web UI)
cancel_scrape: bool = False   # Set when the user asks to stop; long loops check it and stop cleanly
scrapes_running: int = 0      # How many scrapes are in flight; the flag clears when the last one ends
scrape_type: Literal['scrape', 'bulk', 'upload', 'stopped'] = 'stopped'
main_bar: dict = {}
bulk_bar: dict = {}
log_to_file: str = None

# Single-flight guard for bulk imports (scheduled or manual). A second bulk import that starts
# while one is already running is refused rather than queued - see process_bulk_import_from_ui.
bulk_import_lock = threading.Lock()
