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

# Scrape cancellation (user-initiated "Stop" from the web UI)
cancel_scrape: bool = False   # Set when the user asks to stop; long loops check it and stop cleanly
scrapes_running: int = 0      # How many scrapes are in flight; the flag clears when the last one ends