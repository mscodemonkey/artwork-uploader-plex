import os, time, yaml, threading, subprocess, re
from core import globals
from models.instance import Instance
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple, Union, List
from utils.notifications import debug_me, update_log, log_to_file
from utils.utils import elapsed_time, title_cleaner
from services.run_history import RunHistory
from core.enums import FileType, MediaType, RunType, RunTrigger, RunOutcome
from core.constants import DEFAULT_KOMETA_DEBOUNCE, DEFAULT_KOMETA_CONTAINER_NAME, DOCKER_KOMETA_CONFIG_PATH

def match_key(library_map: Dict, title: str, season: int=None, episode: int=None) -> int:
    matching_keys = [key for key in library_map if library_map[key]["title"] == title]
    if not matching_keys:
        matching_keys = [key for key in library_map if library_map[key].get("alt_title", None) == title]
    if season is not None and episode is not None:
        ratingKey = next((key for key in matching_keys if any(asset["season"] == season and asset["episode"] == episode for asset in library_map[key]["updated_assets"])), None)
    elif season is not None:
        ratingKey = next((key for key in matching_keys if any(asset["season"] == season and (asset["episode"] == "Cover" or asset["episode"] is None) for asset in library_map[key]["updated_assets"])), None)
    else:
        ratingKey = next((key for key in matching_keys if any(asset["file_type"] in [FileType.MOVIE_POSTER, FileType.COLLECTION_POSTER.value, FileType.SHOW_COVER.value, FileType.BACKGROUND.value, FileType.SQUARE_ART.value] for asset in library_map[key]["updated_assets"])), None)
    return ratingKey

def match_asset(asset_list: List[Dict], file_type: str, season: int=None, episode: int=None) -> Dict:
    if season is not None and episode is not None:
        match = next((asset for asset in asset_list if asset["file_type"] == file_type and asset["season"] == season and asset["episode"] == episode), None)
    elif season is not None:
        match = next((asset for asset in asset_list if asset["file_type"] == file_type and asset["season"] == season), None)
    else:
        match = next((asset for asset in asset_list if asset["file_type"] == file_type), None)
    return match

def match_library_name(line: str) -> Optional[str]:
    """ Matches either "Applying Overlays for the <LIBRARY> Library" or
        "<LIBRARY> Library Operations" and returns the library name
    """

    clean_line = line.strip().strip("|").strip() # Remove | from start end end of Kometa log line

    pattern = r"(?:Applying\s+Overlays\s+for\s+the\s+(.*?)\s+Library|([^\s].*?)\s+Library\s+Operations)"

    match = re.search(pattern, clean_line, re.IGNORECASE)
    if match:
        # group(1) matches Pattern 1, group(2) matches Pattern 2
        return (match.group(1) or match.group(2)).strip()

    return None

def parse_overlays_log(line: str, title: str) -> Tuple[Optional[int], Optional[int]]:
    clean_line = line.strip().strip("|").strip()  # Remove | from start/end
    clean_line = re.sub(r"^\(\d+/\d+\)\s*", "", clean_line)  # Remove (x/y) progress indicator
    clean_line = re.sub(r"\(\d{4}\)", "", clean_line)  # Remove title year if present
    clean_line = re.sub(r"\s+", " ", clean_line).strip()  # Clean up resulting spaces
    
    title_idx = clean_line.find(title)
    if title_idx == -1:
        return None, None
    remainder = clean_line[title_idx + len(title) :].strip()

    # Flexible match for SxxExx anywhere at the start of remainder
    se_match = re.search(r"^S(\d+)E(\d+)\b", remainder, re.IGNORECASE)
    if se_match:
        return int(se_match.group(1)), int(se_match.group(2))

    # Flexible match for Season xx anywhere at the start of remainder
    season_match = re.search(r"^Season\s+(\d+)\b", remainder, re.IGNORECASE)
    if season_match:
        return int(season_match.group(1)), None

    return None, None

def parse_operations_log(line: str) -> Dict[str, Union[str, int]]:
    pattern = re.compile(
        r"updated\s+(?P<title>.+?)(?:\s+(?:Season\s+(?P<season_num>\d+)|S(?P<s_num>\d+)E(?P<e_num>\d+)))?'s\s+(?P<asset_type>poster|background|square_art)\b",
        re.IGNORECASE
    )
    match = pattern.search(line)
    
    if not match:
        return None

    data = match.groupdict()

    title = data["title"]
    season = data["season_num"] or data["s_num"]
    episode = data["e_num"]

    asset_type = "unknown"
    if episode:
        asset_type = FileType.TITLE_CARD.value
    elif season:
        asset_type = FileType.SEASON_COVER.value
    else:
        asset_type = data["asset_type"]

    return {
        "title": title_cleaner(title),
        "asset_type": asset_type,
        "season": int(season) if season else None,
        "episode": int(episode) if episode else None
    }

def parse_applied_overlays(line: str) -> list[str]:
    pattern = r"Overlay File \(\d+\)\s+([^,|]+)"
    matches = re.findall(pattern, line)
    return [overlay.strip() for overlay in matches]

def parse_error_line(line: str, container_name: str) -> Optional[str]:
    line = line.lower()
    if "no such container" in line:
        return f"Container '{container_name}' does not exist"
    if all(m in line for m in ["container", "is not running"]):
        return f"Container '{container_name}' is not running"
    if (
        all(m in line for m in ["python:", "no such file"])
        or all(m in line for m in ["python", "not found"])
    ):
        return f"Can't find 'kometa.py' in container '{container_name}'"
    return None

class KometaRunner:
    """
    Manages targeted Kometa updates by converting updated media assets
    into temporary YAML configurations and triggering background Kometa executions.
    """

    def __init__(self):
        self._pending_map: Dict[str, Dict[int, str]] = {}
        self._kometa_libraries: List[str] = []
        self._lock = threading.RLock()
        self._timer: Optional[threading.Timer] = None
        self._is_running = False
        self._instance: Optional[Instance] = None
        self._attempts: int = 0

    def set_instance(self, instance: Instance):
        self._instance = instance

    @property
    def config(self):
        return globals.config

    @property
    def config_path(self) -> str:
        if globals.docker:
            return Path(DOCKER_KOMETA_CONFIG_PATH)
        return Path(getattr(self.config, "kometa_config_path", ""))

    @property
    def container_name(self) -> Optional[str]:
        return getattr(self.config, "kometa_container_name", DEFAULT_KOMETA_CONTAINER_NAME)

    @property
    def debounce_seconds(self) -> float:
        return float(getattr(self.config, "kometa_debounce", DEFAULT_KOMETA_DEBOUNCE))

    @property
    def temp_config_path(self) -> Path:
        return Path(os.path.join(self.config_path, "temp_kometa_run.yml"))

    @property
    def is_running(self) -> bool:
        """
        Checks if a targeted Kometa run is currently active by verifying in-memory state
        (for the current process) or the presence of the temp config file (across processes).
        """
        with self._lock:
            if self._is_running:
                return True
        return self.temp_config_path.exists()

    def _cleanup_temp_files(self, temp_path: Path):
        if not temp_path:
            return

        targets = [
            temp_path,
            temp_path.with_suffix(".cache"),
            temp_path.with_suffix(".cache-wal"),
            temp_path.with_suffix(".cache-shm")
        ]

        for file_path in targets:
            try:
                file_path.unlink(missing_ok=True)
                debug_me(f"Cleaned up temp file at {file_path}")
            except Exception as e:
                debug_me(f"Failed to remove temp file {file_path}: {e}")
    
    def enqueue(self, asset_map: Dict[str, Dict[int, str]]):
        """
        Enqueues an updated_asset_map and starts/resets the debounce timer.
        """
        if not asset_map:
            return

        with self._lock:
            total_assets = 0
            for library, items in asset_map.items():
                debug_me(f"Processing {len(items)} items from library {library}")
                debug_me(items)
                total_assets += sum(len(data["updated_assets"]) for data in items.values())
                if library not in self._pending_map:
                    self._pending_map[library] = {}
                self._pending_map[library].update(items)

            num_libs = len(self._pending_map)
            debug_me(f"Enqueued {total_assets} assets across {num_libs} libraries ")
            update_log(self._instance, f"📥 Enqueued {total_assets} asset{'' if total_assets == 1 else 's'} across {num_libs} librar{'y' if num_libs == 1 else 'ies'} for targeted Kometa updates")

            # Reset debounce timer
            if self._timer:
                debug_me("Timer is active, canceling")
                self._timer.cancel()

            debug_me(f"Initiating debounce timer of {self.debounce_seconds} seconds")
            update_log(self._instance, f"⏳ Kometa run due in {int(self.debounce_seconds)} seconds")
            self._timer = threading.Timer(self.debounce_seconds, self._process_queue)
            self._timer.start()

    def _process_queue(self):
        """
        Triggered when debounce timer elapses. Extracts queue state, builds YAML, and executes.
        """
        debug_me(f"Processing queue! {self._pending_map}")
        with self._lock:
            if not self._pending_map:
                return

            if self.is_running:
                self._attempts += 1
                if self._attempts > 2:
                    debug_me(f"Unable to initiate Kometa run, a stale temp_kometa_run.yml file may be present in the config folder")
                    update_log(self._instance, f"🚨 Unable to initiate Kometa run after 3 attempts")
                    self._attempts = 0
                    self._pending_map.clear()
                    return
                debug_me("A Kometa run is already in progress. Re-debouncing queue...")
                update_log(self._instance, f"⏱️ Another Kometa run is already in progress, waiting {int(self.debounce_seconds)} more seconds")
                self._timer = threading.Timer(self.debounce_seconds, self._process_queue)
                self._timer.start()
                return

            self._attempts = 0

            # Snapshot pending items and clear queue
            current_batch = self._pending_map.copy()
            self._pending_map.clear()
            self._is_running = True

        # Run processing in a background worker thread
        threading.Thread(
            target=self._execute_batch_job,
            args=(current_batch,),
            daemon=True
        ).start()

    def _execute_batch_job(self, asset_map: Dict[str, Dict[int, str]]):
        temp_config_path = None

        try:
            temp_config_path = self.generate_targeted_yaml(asset_map)
            debug_me(f"Generated targeted temp config file at: {temp_config_path}")
            
            self._run_kometa_process(temp_config_path, asset_map)

        except Exception as e:
            debug_me(f"Error during Kometa execution: {e}")
            update_log(self._instance, f"❌️ Error encountered during Kometa execution: {e}")

        finally:
            if temp_config_path:
                self._cleanup_temp_files(temp_config_path)            
            with self._lock:
                self._is_running = False

    def run_from_cli(self, asset_map: Dict[str, Dict[int, str]]) -> bool:
        """
        Synchronously executes Kometa for CLI runs while respecting active runs
        """
        if not asset_map:
            return False
        
        temp_config_path = None

        if self.is_running:
            debug_me("Another Kometa run is already in progress, skipping CLI run")
            update_log(self._instance, "⚠️ Another Kometa run is already in progress, skipping update")
            return False

        try:
            temp_config_path = self.generate_targeted_yaml(asset_map)
            self._run_kometa_process(temp_config_path, asset_map)
            return True

        except Exception as e:
            debug_me(f"Error during synchronous Kometa execution: {e}")
            update_log(self._instance, f"❌ Error during Kometa execution: {e}")
            return False

        finally:
            if temp_config_path:
                self._cleanup_temp_files(temp_config_path)
    
    def generate_targeted_yaml(self, batch_map: Dict[str, Dict[int, str]]) -> Path:
        """
        Creates library-specific metadata files and the root targeted config.yml.
        """
        main_config_path = Path(os.path.join(self.config_path, "config.yml"))
        self._kometa_libraries = []

        if not main_config_path.exists():
            raise FileNotFoundError(f"Main Kometa config not found at {main_config_path}")

        with open(main_config_path, "r", encoding="utf-8") as f:
            full_config = yaml.safe_load(f) or {}

        targeted_config = full_config.copy()
        libraries_to_pop = []

        libraries = targeted_config.get("libraries", {})
        if not libraries:
            raise Exception(f"No libraries defined in Kometa's config.yml file")

        for lib_name, lib_data in libraries.items():
            if lib_name not in batch_map:
                libraries_to_pop.append(lib_name)
                continue
            self._kometa_libraries.append(lib_name)
            libraries[lib_name].pop("collection_files", None)
            if lib_data.get("operations", None):
                lib_data["operations"].pop("assets_for_all_collections", None)

        if "settings" not in targeted_config:
            targeted_config["settings"] = {}

        targeted_config["settings"]["show_unmanaged"] = False
        targeted_config["settings"]["show_unconfigured"] = False
        targeted_config["settings"]["run_order"] = ['operations', 'overlays']

        for lib in libraries_to_pop:
            libraries.pop(lib, None)
    
        if not targeted_config.get("libraries", None):
            raise Exception(f"None of the updated libraries are present in Kometa's config.yml file")

        root_config_path = os.path.join(self.config_path, "temp_kometa_run.yml")
        with open(root_config_path, "w", encoding="utf-8") as f:
            yaml.dump(targeted_config, f, default_flow_style=False, allow_unicode=True)

        return Path(root_config_path)

    def _run_kometa_process(self, config_path, batch_map: Dict[str, Dict[int, str]]):
        """
        Executes Kometa via Docker Exec or Native Python subprocess.
        """
        args_operations = ""
        args_overlays = ""
        overlay_assets = [FileType.MOVIE_POSTER.value, FileType.SHOW_COVER.value, FileType.POSTER.value, FileType.TITLE_CARD, FileType.SEASON_COVER]
        items_operations = set()
        libs_operations = set()
        titles_operations = set()
        items_overlays = set()
        libs_overlays = set()
        titles_overlays = set()

        for library, items in batch_map.items():
            if library not in self._kometa_libraries:
                debug_me(f"Library {library} is not present in Kometa config.yml file, skipping")
                update_log(self._instance, f"⚠️ Library {library} is not present in Kometa's config.yml file")
                continue
           
            debug_me(f"Processing updated items for library {library}")

            for key, item in items.items():
                updated_assets = item["updated_assets"]
                if any(asset["file_type"] in overlay_assets and asset["overlay"] for asset in updated_assets):
                    items_overlays.add(key)
                    libs_overlays.add(library)
                    titles_overlays.add(item.get("alt_title", item["title"]))
                if not all(asset["file_type"] in overlay_assets and asset["overlay"] for asset in updated_assets):
                    items_operations.add(key)
                    libs_operations.add(library)
                    titles_operations.add(item.get("alt_title", item["title"]))
            
        args_operations = "|".join([f"plex:{key}" for key in items_operations])
        args_libs_ops = "|".join(libs_operations)
        debug_me(f"Arguments for operations: Libraries [{args_libs_ops}], Items [{args_operations}]")
        debug_me(f"Operations titles: {titles_operations}")
        args_overlays = "|".join([f"plex:{key}" for key in items_overlays])
        args_libs_ovs = "|".join(libs_overlays)
        debug_me(f"Arguments for overlays: Libraries [{args_libs_ovs}], Items [{args_overlays}]")
        debug_me(f"Overlays titles: {titles_overlays}")

        config_filename = config_path.name

        if args_operations:
            start_time = time.time()
            started_at = datetime.now(timezone.utc).isoformat()
            run_label = "kometa_operations"
            log_to_file(run_label)

            update_log(self._instance, f"⚙️ Starting Kometa operations run for {len(titles_operations)} media item{'s' if len(titles_operations) > 1 else ''} in {len(libs_operations)} librar{'ies' if len(libs_operations) > 1 else 'y'} [{', '.join(libs_operations)}]")
            refreshed_assets = 0
            
            cmd = [
                "docker","exec",
                "-e", f"KOMETA_CONFIG=config/{config_filename}",
                "-e", f"KOMETA_OPERATIONS_ONLY=true",
                "-e", f"KOMETA_OVERLAYS_ONLY=false",
                "-e", f"KOMETA_METADATA_ONLY=false",
                "-e", f"KOMETA_COLLECTIONS_ONLY=false",
                "-e", f"KOMETA_PLAYLISTS_ONLY=false",
                "-e", f"KOMETA_RUN_LIBRARIES={args_libs_ops}",
                "-e", f"KOMETA_MODE=items({args_operations})",
                self.container_name,
                "python",
                "kometa.py"
            ]

            debug_me(f"Launching command: [{' '.join(cmd)}]")

            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    encoding="utf-8",
                    errors="replace",
                    text=True,
                    bufsize=1
                )

                # Stream output logs
                current_library = ""
                error_detail = None

                for line in process.stdout:
                    stripped = line.strip()
                    debug_me(stripped)
                    error_detail = parse_error_line(stripped, self.container_name) or error_detail

                    matched_library = match_library_name(line.strip()[1:-2])
                    if matched_library and matched_library in libs_operations:
                        current_library = matched_library
                        this_library = batch_map[current_library]

                    match = parse_operations_log(line.strip())
                    if match:
                        title = match["title"]
                        season = match.get("season", None)
                        episode = match.get("episode", None)

                        ratingKey = match_key(
                            library_map=this_library,
                            title=title,
                            season=season,
                            episode=episode
                        )

                        if not ratingKey:
                            debug_me("Unable to match asset, skipping")
                            continue

                        season_label = f" • Season {season:02}" if season is not None and season != 0 else f" • Specials" if season is not None else ""
                        episode_label = f" • Episode {episode:02}" if episode else ""

                        this_item = this_library[ratingKey]
                        updated_assets = this_item["updated_assets"]

                        media_type = this_item["media_type"]

                        matched_type = match["asset_type"]
                        if matched_type == "poster":
                            if media_type == MediaType.MOVIE.value:
                                file_type = FileType.MOVIE_POSTER.value
                                asset_type = "Movie poster"
                            elif media_type == MediaType.TV_SHOW.value:
                                file_type = FileType.SHOW_COVER.value
                                asset_type = "Show cover"
                            elif media_type == MediaType.COLLECTION.value:
                                file_type = FileType.COLLECTION_POSTER.value
                                asset_type = "Collection poster"
                        elif matched_type == "background":
                            file_type = FileType.BACKGROUND.value
                            asset_type = f"{media_type} background"
                        elif matched_type == "square_art":
                            file_type = FileType.SQUARE_ART.value
                            asset_type = f"{media_type} square art"
                        elif matched_type == "season_cover":
                            file_type = FileType.SEASON_COVER.value
                            asset_type = "Season cover"
                        elif matched_type == "title_card":
                            file_type = FileType.TITLE_CARD.value
                            asset_type = "Title card"

                        updated_asset = match_asset(
                            asset_list=updated_assets,
                            file_type=file_type,
                            season=season,
                            episode=episode
                        )

                        if not updated_asset:
                            debug_me("Unable to match asset, skipping")
                            continue

                        author = updated_asset["author"]

                        title = this_item.get("alt_title", this_item["title"])
                        year = this_item["year"]
                        desc = f"{title}{f' ({year})' if year is not None else ''} • {author}{season_label}{episode_label}"
                        
                        if updated_asset.get("status", None) == "new":
                            text = f"✅ {desc} | {asset_type} set by Kometa in {current_library}"
                        else:
                            text = f"♻️ {desc} | {asset_type} refreshed by Kometa in {current_library}"
                        update_log(self._instance, text)
                        refreshed_assets += 1
                        
                process.wait()
                if process.returncode == 0:
                    end_time = time.time()
                    process_time = elapsed_time(end_time - start_time)
                    debug_me(f"Targeted Kometa operations run completed successfully. {refreshed_assets} asset(s) refreshed in Plex in {process_time}.")
                    update_log(self._instance, f"✔️ Targeted Kometa operations run completed successfully. {refreshed_assets} asset{'s' if refreshed_assets > 1 else ''} refreshed in Plex in {process_time}.")
                    run_outcome = RunOutcome.SUCCESS.value
                    
                else:
                    reason = error_detail or f"Return code {process.returncode}"
                    debug_me(f"Kometa exited with error message: {reason}")
                    update_log(self._instance, f"❌️ Error encountered during Kometa operations run: {reason}")
                    run_outcome = RunOutcome.FAILED.value
        
            except FileNotFoundError:
                debug_me("'docker' CLI command not found. Is docker installed/mounted in Artwork Uploader?")
                update_log(self._instance, f"❌️ Error: 'docker' CLI command not found. Is docker installed/mounted in Artwork Uploader?")
                run_outcome = RunOutcome.FAILED.value

            except Exception as e:
                debug_me(f"Unexpected error running Kometa container: {e}")
                update_log(self._instance, f"❌️ Unexpected error running Kometa container: {e}")
                run_outcome = RunOutcome.FAILED.value

            ended_at = datetime.now(timezone.utc).isoformat()
            RunHistory().add_run(
                run_type=RunType.KOMETA.value,
                label=run_label,
                started_at=started_at,
                ended_at=ended_at,
                trigger=RunTrigger.AUTO.value,
                outcome=run_outcome,
                assets_processed=refreshed_assets,
                success_count=refreshed_assets
            )
            
        else:
            debug_me("No operations run required")
        
        if args_overlays:
            start_time = time.time()
            started_at = datetime.now(timezone.utc).isoformat()
            run_label = "kometa_overlays"
            log_to_file(run_label)

            update_log(self._instance, f"⚙️ Starting Kometa overlays run for {len(titles_overlays)} media item{'s' if len(titles_overlays) > 1 else ''} in {len(libs_overlays)} librar{'ies' if len(libs_overlays) > 1 else 'y'} [{', '.join(libs_overlays)}]")

            refreshed_assets = 0
            overlays_applied = 0

            cmd = [
                "docker","exec",
                "-e", f"KOMETA_CONFIG=config/{config_filename}",
                "-e", f"KOMETA_OVERLAYS_ONLY=true",
                "-e", f"KOMETA_OPERATIONS_ONLY=false",
                "-e", f"KOMETA_METADATA_ONLY=false",
                "-e", f"KOMETA_COLLECTIONS_ONLY=false",
                "-e", f"KOMETA_PLAYLISTS_ONLY=false",
                "-e", f"KOMETA_RUN_LIBRARIES={args_libs_ovs}",
                "-e", f"KOMETA_MODE=items({args_overlays})",
                self.container_name,
                "python",
                "kometa.py"
            ]

            debug_me(f"Launching command: [{' '.join(cmd)}]")

            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    encoding="utf-8",
                    errors="replace",
                    text=True,
                    bufsize=1
                )

                # Stream output logs
                capture_next_line = False
                current_library = ""
                error_detail = None

                for line in process.stdout:
                    stripped = line.strip()
                    debug_me(stripped)
                    error_detail = parse_error_line(stripped, self.container_name) or error_detail
                    
                    matched_library = match_library_name(line.strip())
                    if matched_library and matched_library in libs_overlays:
                        current_library = matched_library
                        this_library = batch_map[current_library]

                    matched_title = next((title for title in titles_overlays if title in line), None)
                    if matched_title:
                        season, episode = parse_overlays_log(line.strip(), matched_title)

                        season_label = f" • Season {season:02}" if season is not None and season != 0 else f" • Specials" if season is not None else ""
                        episode_label = f" • Episode {episode:02}" if episode else ""

                        capture_next_line = True
                        captured_title = matched_title
                        continue

                    if capture_next_line:
                        capture_next_line = False
                        if "Overlays Applied" not in line:
                            continue

                        ratingKey = match_key(
                            library_map=this_library,
                            title=captured_title,
                            season=season,
                            episode=episode
                        )
                        if not ratingKey:
                            debug_me("Unable identify ratingKey for asset, skipping")
                            continue

                        this_item = this_library[ratingKey]
                        title = this_item.get("alt_title", this_item["title"])
                        year = this_item["year"]
                        media_type = this_item["media_type"]
                        media_to_file_map = {
                            MediaType.MOVIE.value: {
                                "file_type": FileType.MOVIE_POSTER.value,
                                "label": "Movie poster"
                            },
                            MediaType.TV_SHOW.value: {
                                "file_type": FileType.SHOW_COVER.value,
                                "label": "Show cover"
                            }
                        }

                        if season and episode:
                            file_type = FileType.TITLE_CARD.value
                            asset_type = "Title card"
                        elif season:
                            file_type = FileType.SEASON_COVER.value
                            asset_type = "Season cover"
                        else:
                            file_type = media_to_file_map[media_type]["file_type"]
                            asset_type = media_to_file_map[media_type]["label"]

                        updated_assets = this_item["updated_assets"]
                        updated_asset = match_asset(
                            asset_list=updated_assets,
                            file_type=file_type,
                            season=season,
                            episode=episode
                        )
                        if not updated_asset:
                            debug_me("Unable to match asset, skipping")
                            continue

                        author = updated_asset["author"]

                        desc = f"{title}{f' ({year})' if year else ''}{f' • {author}' if author else ''}{season_label}{episode_label}"
                        
                        applied_overlays = parse_applied_overlays(line)

                        if updated_asset.get("status", None) == "new":
                            update_log(self._instance, f"✅ {desc} | {asset_type} set and [{", ".join(applied_overlays)}] overlay{'s' if len(applied_overlays) > 1 else ''} applied in {current_library}")
                        else:
                            update_log(self._instance, f"♻️ {desc} | {asset_type} refreshed and [{", ".join(applied_overlays)}] overlay{'s' if len(applied_overlays) > 1 else ''} applied in {current_library}")
                        refreshed_assets += 1
                        overlays_applied += len(applied_overlays)

                process.wait()
                if process.returncode == 0:
                    end_time = time.time()
                    process_time=elapsed_time(end_time - start_time)
                    debug_me(f"Targeted Kometa overlays run completed successfully. {refreshed_assets} assets refreshed and {overlays_applied} overlays applied in {process_time}.")
                    update_log(self._instance, f"✔️ Targeted Kometa overlays run completed successfully. {refreshed_assets} asset{'s' if refreshed_assets > 1 else ''} refreshed and {overlays_applied} overlay{'s' if overlays_applied > 1 else ''} applied in {process_time}.")
                    run_outcome = RunOutcome.SUCCESS.value
                else:
                    reason = error_detail or f"Return code {process.returncode}"
                    debug_me(f"Kometa exited with error message: {reason}")
                    update_log(self._instance, f"❌️ Error encountered during Kometa overlays run: {reason}")
                    run_outcome = RunOutcome.FAILED.value
        
            except FileNotFoundError:
                debug_me("'docker' CLI command not found. Is docker installed/mounted in Artwork Uploader?")
                update_log(self._instance, f"❌️ Error: 'docker' CLI command not found. Is docker installed/mounted in Artwork Uploader?")
                run_outcome = RunOutcome.FAILED.value

            except Exception as e:
                debug_me(f"Unexpected error running Kometa container: {e}")
                update_log(self._instance, f"❌️ Unexpected error running Kometa container: {e}")
                run_outcome = RunOutcome.FAILED.value

            ended_at = datetime.now(timezone.utc).isoformat()
            RunHistory().add_run(
                run_type=RunType.KOMETA.value,
                label=run_label,
                started_at=started_at,
                ended_at=ended_at,
                trigger=RunTrigger.AUTO.value,
                outcome=run_outcome,
                assets_processed=refreshed_assets,
                success_count=refreshed_assets
            )

        else:
            debug_me("No overlays run required")
