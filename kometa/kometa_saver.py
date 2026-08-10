import os, requests, mimetypes, time
from typing import Optional
from utils.notifications import debug_me
from models.options import Options
from core.enums import ScraperSource
from core.constants import IMAGE_EXTENSIONS, DEFAULT_KOMETA_DOWNLOAD_TIMEOUT, DEFAULT_UPLOAD_RETRY_ATTEMPTS, DEFAULT_UPLOAD_RETRY_BACKOFF_SECONDS
from core.retry import call_with_retry
from models.artwork_types import AnyArtwork

class KometaSaver:

    def __init__(
        self,
        artwork_type: str,
        library: str,
    ) -> None:
        self.artwork_type: str = artwork_type
        self.library: str = library
        self.description: str = "item"
        self.kometa_base: str = ""
        self.dest_dir: str = ""
        self.dest_file_name: str = "poster"
        self.dest_file_ext: str = ".jpg"
        self.type: Optional[str] = None
        self.artwork: Optional[AnyArtwork] = None
        self.options: Options = Options()
        self.confirm_match = None
        self.download_timeout: int = DEFAULT_KOMETA_DOWNLOAD_TIMEOUT
        self.retry_attempts: int = DEFAULT_UPLOAD_RETRY_ATTEMPTS
        self.retry_backoff: float = DEFAULT_UPLOAD_RETRY_BACKOFF_SECONDS

    def set_artwork(self, artwork: AnyArtwork) -> None:
        self.artwork = artwork
        if artwork['id'] == ScraperSource.UPLOAD.value:
            self.type = "file"
        else:
            self.type = "url"

    def set_description(self, description: str) -> None:
        self.description = description

    def set_options(self, options: Options) -> None:
        if isinstance(options, Options):
            self.options = options
        
    def save_to_kometa(self) -> str:

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }

        replaced_file: bool = False
        existing_file: Optional[str] = None

        # Check if an asset already exists for this item, skip if so (unless force is specified, in which case delete existing asset first)
        try:
            for check_ext in IMAGE_EXTENSIONS:
                existing_file = os.path.join(self.dest_dir, f"{self.dest_file_name}{check_ext}")
                if os.path.exists(existing_file) and not self.options.force:
                    return f"⏩ {self.description} | {self.artwork_type} skipped (already exists) for {self.library}"
                elif os.path.exists(existing_file) and self.options.force:
                    #os.remove(existing_file)
                    replaced_file = True
                    break
        except OSError as e:
            return f"❌ {self.description} | Error checking existing {self.artwork_type.lower()} asset: {e}"

        if self.confirm_match is not None and not self.confirm_match():
            return f"⚠️ {self.description} | {self.artwork_type} skipped for {self.library} - artwork is for a different title"

        if self.type == "file":
            # Save from local file path
            source_file = self.artwork['path']
            self.dest_file_ext = os.path.splitext(source_file)[1]  # Use the original file extension
            dest_file = os.path.join(self.dest_dir, f"{self.dest_file_name}{self.dest_file_ext}")
            try:
                os.makedirs(self.dest_dir, exist_ok=True)
                with open(source_file, 'rb') as src_f:
                    with open(dest_file, 'wb') as dest_f:
                        dest_f.write(src_f.read())
                if replaced_file:
                    return f"♻️ {self.description} | {self.artwork_type} replaced at '{dest_file}' in {self.library}"
                else:
                    return f"✅ {self.description} | {self.artwork_type} saved at '{dest_file}' in {self.library}"
            except OSError:
                return f"❌ {self.description} | Error saving {self.artwork_type.lower()} (invalid path): '{self.dest_dir}'"
            except Exception as e:
                return f"❌ {self.description} | Failed to save {self.artwork_type.lower()}: {e}"
        try:
            url = self.artwork["url"]
            debug_me(f"Downloading {self.artwork_type.lower()} from URL: {url}")

            def _fetch():
                response = requests.get(url, headers=headers, stream=True, timeout=self.download_timeout)
                response.raise_for_status()
                return response

            # A timeout, dropped connection, or 5xx is worth trying again; anything else (a 429,
            # a 404) fails immediately rather than burning the retry budget.
            r, _ = call_with_retry(_fetch, self.retry_attempts, self.retry_backoff)
            content_type = r.headers.get('Content-Type', '')
            ext = mimetypes.guess_extension(content_type.split(';')[0])
            self.dest_file_ext = ext if ext is not None else self.dest_file_ext
        except requests.exceptions.Timeout as e:
            attempts = getattr(e, "attempts", 1)
            attempts_note = f" after {attempts} attempt(s)" if attempts > 1 else ""
            debug_me(f"Downloading asset from {url} timed out ({self.download_timeout} seconds){attempts_note}: {str(e)}")
            return f"❌ {self.description} | Error saving {self.artwork_type.lower()}: Asset download timed out ({self.download_timeout} seconds){attempts_note}"
        except requests.exceptions.ConnectionError as e:
            attempts = getattr(e, "attempts", 1)
            attempts_note = f" after {attempts} attempt(s)" if attempts > 1 else ""
            debug_me(f"Connection error{attempts_note}: {str(e)}")
            return f"❌ {self.description} | Error saving {self.artwork_type.lower()}: Could not connect to server, check your internet connection or the site's status{attempts_note}"
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            attempts = getattr(e, "attempts", 1)
            attempts_note = f" after {attempts} attempt(s)" if attempts > 1 else ""
            if status == 429:
                debug_me(f"Obtained error 429: too many requests (connection has been rate-limited)")
                return f"❌ {self.description} | Error saving {self.artwork_type.lower()}: Too many requets (connection rate-limtied)"
            else:
                debug_me(f"HTTP status code {status}{attempts_note}")
                return f"❌ {self.description} | Error saving {self.artwork_type.lower()}: HTTP Error: {status}{attempts_note}"
        except Exception as e:
            debug_me(f"❌ {self.description} | Error saving {self.artwork_type.lower()}: Unknown error")
            raise

        dest_file = os.path.join(self.dest_dir, f"{self.dest_file_name}{self.dest_file_ext}")
        temp_file = f"{dest_file}.tmp"
        try:
            os.makedirs(self.dest_dir, exist_ok=True)
            with open(temp_file, 'wb') as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            if replaced_file and existing_file != dest_file:
                os.remove(existing_file)
            os.replace(temp_file, dest_file)
            if self.artwork['source'] == ScraperSource.THEPOSTERDB:
                time.sleep(1)
            if replaced_file:
                return f"♻️ {self.description} | {self.artwork_type} replaced at '{dest_file}' in {self.library}"
            else:
                return f"✅ {self.description} | {self.artwork_type} saved at '{dest_file}' in {self.library}"
        except OSError:
            return f"❌ {self.description} | Error saving {self.artwork_type.lower()} (invalid path): '{self.dest_dir}'"
        except Exception as e:
            return f"❌ {self.description} | Failed to save {self.artwork_type.lower()}: {e}"

