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