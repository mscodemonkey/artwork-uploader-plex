import os, time, yaml, logging, threading, subprocess
from core.config import Config
from core import globals
from pathlib import Path
from typing import Dict, Optional
from utils.notifications import debug_me, update_log

class KometaRunner:
    """
    Manages targeted Kometa updates by converting updated media assets
    into temporary YAML configurations and triggering background Kometa executions.
    """

    def __init__(self):
        # Pending items accumulated across runs: dict[library_name, dict[tmdb_id, title]]
        self._pending_map: Dict[str, Dict[int, str]] = {}
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._is_running = False

    @property
    def config(self):
        return globals.config

    @property
    def config_path(self) -> str:
        return Path(getattr(self.config, "kometa_config_path", ""))

    # @property
    # def app_path(self) -> str:
    #     return getattr(self.config, "kometa_app_path", "")

    @property
    def container_name(self) -> Optional[str]:
        return getattr(self.config, "kometa_container_name", None)

    # @property
    # def is_docker(self) -> bool:
    #     return self.container_name is not None

    @property
    def debounce_seconds(self) -> float:
        return float(getattr(self.config, "kometa_debounce", 10))
    
    def enqueue(self, asset_map: Dict[str, Dict[int, str]]):
        """
        Enqueues an updated_asset_map and starts/resets the debounce timer.
        """
        if not asset_map:
            return

        with self._lock:
            for library, items in asset_map.items():
                debug_me(f"Processing {items} from library {library}")
                if library not in self._pending_map:
                    self._pending_map[library] = {}
                self._pending_map[library].update(items)

            total_items = sum(len(items) for items in self._pending_map.values())
            debug_me(f"Enqueued assets across {len(self._pending_map)} libraries ")
            debug_me(f"({total_items} total unique items pending).")

            # Reset debounce timer
            if self._timer:
                debug_me("Timer is active, canceling")
                self._timer.cancel()

            debug_me(f"Initiating debounce timer of {self.debounce_seconds}")
            self._timer = threading.Timer(self.debounce_seconds, self._process_queue)
            self._timer.start()
            debug_me(f"self._pending_map is {self._pending_map}")

    def _process_queue(self):
        """
        Triggered when debounce timer elapses. Extracts queue state, builds YAML, and executes.
        """
        debug_me(f"Processing queue! {self._pending_map}")
        with self._lock:
            if not self._pending_map:
                return

            if self._is_running:
                debug_me("A Kometa run is already in progress. Re-debouncing queue...")
                self._timer = threading.Timer(self.debounce_seconds, self._process_queue)
                self._timer.start()
                return

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

    def _execute_batch_job(self, batch_map: Dict[str, Dict[int, str]]):
        try:
            temp_config_path = self.generate_targeted_yaml(batch_map)
            debug_me(f"Generated targeted config at: {temp_config_path}")

            return
            self._run_kometa_process(temp_config_path)

        except Exception as e:
            debug_me(f"Error during Kometa execution: {e}")
        finally:
            with self._lock:
                self._is_running = False

    def generate_targeted_yaml(self, batch_map: Dict[str, Dict[int, str]]) -> Path:
        """
        Creates library-specific metadata files and the root targeted config.yml.
        """
        main_config_path = Path(os.path.join(self.config_path, "config.yml"))

        if not main_config_path.exists():
            raise FileNotFoundError(f"Main Kometa config not found at {main_config_path}")

        with open(main_config_path, "r", encoding="utf-8") as f:
            full_config = yaml.safe_load(f) or {}

        targeted_config = {
            "plex": full_config.get("plex", {}),
            "tmdb": full_config.get("tmdb", {}),
            "settings": full_config.get("settings", {}),
            "libraries": {}
        }

        existing_libraries = full_config.get("libraries", {})
        debug_me(f"Obtained existing libraries from yaml file: {existing_libraries.keys()}")
        
        # self.config_path.mkdir(parents=True, exist_ok=True)
        # libraries_config = {}

        for library_name, items in batch_map.items():
            debug_me(f"Processing library {library_name}")
            if not items:
                continue

            # Safe filename slug for metadata file
            slug = "".join(c if c.isalnum() else "_" for c in library_name.lower())
            meta_filename = f"temp_meta_{slug}.yml"
            meta_path = os.path.join(self.config_path, meta_filename)

            # Build metadata block with TMDb search rules
            meta_content = {
                "metadata": {
                    f"Targeted Updates - {library_name}": {
                        "plex_search": {
                            "any": {
                                "tmdb_id": list(items.keys())
                            }
                        }
                    }
                }
            }

            with open(meta_path, "w", encoding="utf-8") as f:
                yaml.dump(meta_content, f, default_flow_style=False, allow_unicode=True)

            lib_original = existing_libraries.get(library_name, {})
            print("#"*100)
            debug_me(lib_original)
            settings = lib_original.get("settings", {})
            print("#"*100)
            debug_me(settings)
            operations = lib_original.get("operations", {})
            print("#"*100)
            debug_me(operations)
            overlay_files = lib_original.get("overlay_files", {})
            print("#"*100)
            debug_me(overlay_files)

            targeted_config["libraries"][library_name] = {
                "settings": lib_original.get("settings", {}),
                "operations": lib_original.get("operations", {}),
                "overlay_files": lib_original.get("overlay_files", {}),
                "metadata_files": [
                    {"file": f"config/{meta_filename}"}
                ]
            }

        #     libraries_config[library_name] = {
        #         "metadata_files": [
        #             {"file": f"config/{meta_filename}"}
        #         ]
        #     }

        # # Build root config file
        # root_config = {
        #     "libraries": libraries_config
        # }

        root_config_path = os.path.join(self.config_path, "temp_kometa_run.yml")
        with open(root_config_path, "w", encoding="utf-8") as f:
            yaml.dump(targeted_config, f, default_flow_style=False, allow_unicode=True)

        return Path(root_config_path)

    def _run_kometa_process(self, config_path: Path):
        """
        Executes Kometa via Docker Exec or Native Python subprocess.
        """
        config_filename = config_path.name

        # if self.is_docker:
        cmd = [
            "docker",
            "exec",
            self.container_name,
            "python",
            "kometa.py",
            "--config",
            f"/config/{config_filename}",
            "--run"
        ]
        # else: # Native execution
        #     cmd = [
        #         "python", self.kometa_script_path,
        #         "--config", str(config_path),
        #         "--run"
        #     ]

        debug_me(f"Launching command: {' '.join(cmd)}")

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Stream output logs
            for line in process.stdout:
                debug_me(f"{line.strip()}")

            process.wait()
            if process.returncode == 0:
                debug_me("Targeted Kometa run completed successfully.")
            else:
                debug_me(f"Kometa exited with return code {process.returncode}")
        
        except FileNotFoundError:
            debug_me("'docker' CLI command not found. Is docker installed/mounted in Artwork Uploader?")
        except Exception as e:
            debug_me(f"Unexpected error running Kometa container: {e}")