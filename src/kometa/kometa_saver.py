import mimetypes
import os
from typing import Optional

import requests
from core.constants import IMAGE_EXTENSIONS, TPDB_RATE_LIMIT_DELAY
from core.enums import ScraperSource, ArtworkIDPrefix
from models.artwork_types import AnyArtwork
from models.options import Options
from utils import utils
from utils.notifications import debug_me


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

    @staticmethod
    def _remove_quietly(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    def _install_new_asset(self, temp_file: str, dest_file: str, existing_files: list[str]) -> None:
        """Atomically move the new asset into place, then clear out any stale assets
        with a different extension left over from previous runs."""
        os.replace(temp_file, dest_file)
        for stale_file in existing_files:
            if stale_file != dest_file:
                self._remove_quietly(stale_file)

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
        existing_files: list[str] = []

        # Check if an asset already exists for this item, skip if so (unless force is specified). Existing
        # assets are only removed AFTER the replacement has landed (see _install_new_asset) so a failed
        # download or copy can never destroy the user's current artwork.
        try:
            for check_ext in IMAGE_EXTENSIONS:
                existing_file = os.path.join(
                    self.dest_dir, f"{self.dest_file_name}{check_ext}")
                if os.path.exists(existing_file):
                    if not self.options.force:
                        return f"⏩ {self.description} | {self.artwork_type} skipped (already exists) for {self.library}"
                    replaced_file = True
                    existing_files.append(existing_file)
        except OSError as e:
            return f"❌ {self.description} | failed to save {self.artwork_type} asset: {e}"

        if self.type == "file":
            # Save from local file path
            source_file = self.artwork['path']
            self.dest_file_ext = os.path.splitext(
                source_file)[1]  # Use the original file extension
            dest_file = os.path.join(
                self.dest_dir, f"{self.dest_file_name}{self.dest_file_ext}")
            temp_file = f"{dest_file}.tmp"
            try:
                os.makedirs(self.dest_dir, exist_ok=True)
                with open(source_file, 'rb') as src_f:
                    with open(temp_file, 'wb') as dest_f:
                        dest_f.write(src_f.read())
                self._install_new_asset(temp_file, dest_file, existing_files)
                if replaced_file:
                    return f"♻️ {self.description} | {self.artwork_type} replaced at '{dest_file}' in {self.library}"
                else:
                    return f"✅ {self.description} | {self.artwork_type} saved at '{dest_file}' in {self.library}"
            except OSError as e:
                self._remove_quietly(temp_file)
                return f"❌ {self.description} | Error saving {self.artwork_type} (invalid path): '{self.dest_dir}'. {e}"
            except Exception as e:
                self._remove_quietly(temp_file)
                return f"❌ {self.description} | Failed to save {self.artwork_type}: {e}"
        try:
            url = self.artwork["url"]
            debug_me(
                f"Downloading {self.artwork_type} from URL: {url}", "KometaSaver/save_to_kometa")
            r = requests.get(url, headers=headers, stream=True, timeout=5)
            r.raise_for_status()
            content_type = r.headers.get('Content-Type', '')
            ext = mimetypes.guess_extension(content_type.split(';')[0])
            self.dest_file_ext = ext if ext is not None else self.dest_file_ext
        except requests.exceptions.Timeout as e:
            debug_me(f"Downloading asset from {url} timed out (5 seconds): {e}",
                     "KometaSaver/save_to_kometa")
            return f"❌ {self.description} | Error saving {self.artwork_type}: asset download timed out (5 seconds)"
        except requests.exceptions.ConnectionError as e:
            debug_me(f"Connection error: {e}", "KometaSaver/save_to_kometa")
            return f"❌ {self.description} | Error saving {self.artwork_type}: could not connect to server"
        except requests.exceptions.HTTPError:
            if r.status_code == 429:
                return f"❌ {self.description} | Error saving {self.artwork_type}: too many requests (rate-limited)"
            return f"❌ {self.description} | Error saving {self.artwork_type}: HTTP error {r.status_code}"
        except Exception as e:
            return f"❌ {self.description} | Error saving {self.artwork_type}: Error fetching URL: {e}"

        dest_file = os.path.join(
            self.dest_dir, f"{self.dest_file_name}{self.dest_file_ext}")
        temp_file = f"{dest_file}.tmp"
        try:
            os.makedirs(self.dest_dir, exist_ok=True)
            with open(temp_file, 'wb') as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            self._install_new_asset(temp_file, dest_file, existing_files)
            if replaced_file:
                return f"♻️ {self.description} | {self.artwork_type} replaced at '{dest_file}' in {self.library}"
            else:
                return f"✅ {self.description} | {self.artwork_type} saved at '{dest_file}' in {self.library}"
        except OSError as e:
            self._remove_quietly(temp_file)
            return f"❌ {self.description} | Error saving {self.artwork_type} (invalid path): '{self.dest_dir}'. {e}"
        except Exception as e:
            self._remove_quietly(temp_file)
            return f"❌ {self.description} | Failed to save {self.artwork_type}: {e}"
