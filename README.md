<p align="center">
  <img src="assets/banner.png" alt="Artwork Uploader for Plex" width="600">
</p>

<p align="center">
  Upload poster sets from ThePosterDB and MediUX to your Plex server, or save them to your Kometa asset directory, in seconds.
</p>

<p align="center">
  <a href="https://github.com/mscodemonkey/artwork-uploader-plex/actions/workflows/tests.yml"><img src="https://github.com/mscodemonkey/artwork-uploader-plex/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/mscodemonkey/artwork-uploader-plex/releases/latest"><img src="https://img.shields.io/github/v/release/mscodemonkey/artwork-uploader-plex" alt="Latest release"></a>
  <a href="https://github.com/mscodemonkey/artwork-uploader-plex/pkgs/container/artwork-uploader"><img src="https://img.shields.io/badge/ghcr.io-artwork--uploader-2496ED?logo=docker&logoColor=white" alt="Docker image"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white" alt="Python 3.12+">
</p>

---

Artwork Uploader takes a poster set URL (or a downloaded Zip file) from [ThePosterDB](https://theposterdb.com) or [MediUX](https://mediux.pro) and applies the artwork to the matching movies, shows, seasons, episodes and collections in your Plex libraries. Run it from the web UI, the command line, or on a schedule, and let it keep your libraries beautiful while you sleep.

It started life as a fork of Brian Brown's [plex-poster-set-helper](https://github.com/bbrown430/plex-poster-set-helper) and has grown into a full application with a web UI, a scheduler, artwork tracking, Sonarr/Radarr webhooks and Kometa integration.

![Scraper tab](assets/ScraperTab.png)

## Contents

- [Features](#features)
- [Installation](#installation)
  - [Docker (recommended)](#docker-recommended)
  - [Unraid](#unraid)
  - [From source](#from-source)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Web UI](#web-ui)
  - [Command line](#command-line)
  - [Bulk files](#bulk-files)
  - [Scheduler and notifications](#scheduler-and-notifications)
  - [Automatic artwork for new imports (Sonarr/Radarr webhook)](#automatic-artwork-for-new-imports-sonarrradarr-webhook)
  - [Kometa integration](#kometa-integration)
- [Screenshots](#screenshots)
- [Troubleshooting](#troubleshooting)
- [For developers](#for-developers)
- [Thanks](#thanks)

## Features

**Artwork sources**
- Scrape sets and boxsets from ThePosterDB and MediUX by URL.
- Upload the Zip files you download from either site, including the odd misnamed file from MediUX. This also keeps ThePosterDB happy that we're not breaking their terms of service by scraping.
- Grab additional sets and additional posters from the same ThePosterDB page (`--add-sets`, `--add-posters`), useful for big sets like the Marvel or Disney movies. Scraping is against ThePosterDB's terms of service, so we encourage you to log in, download the Zip and upload it with this tool instead. Once an API is available we'll switch over ASAP.

**Speed**
- Artwork tracking: we (optionally) store an artwork ID in a Plex label against each item, so a re-run skips anything that hasn't changed and finishes in a fraction of the time. Use `--force` when you really do want it re-uploaded.
- User scrape caching (`cache_user_scrapes`): a local index of each ThePosterDB user's uploads means repeat scrapes only fetch what's new instead of re-crawling the whole catalogue.
- Local library matching (`local_library_matching`): big user scrapes skip everything you don't own without a single web request, so full-catalogue runs take minutes rather than hours.

**Control**
- Per-URL filters, so one line can upload only title cards while another uploads everything.
- Exclude individual posters by ID, or whole seasons and episodes (`--exclude s02`, `--exclude s01e05`).
- Skip locked artwork (`skip_locked_artwork`), so scheduled runs fill the gaps and leave anything you've set by hand alone.
- Artist updates (`allow_artist_updates`): let a scheduled run move to an artist's newer version of artwork it applied earlier, without ever touching your manual choices.
- Year matching (`--year`) for when Plex and the artwork site disagree about a release year.

**Automation**
- A scheduler with daily fixed-time and interval schedules per bulk file, missed-run catchup, and push notifications through [Apprise](https://appriseit.com/services/).
- Sonarr/Radarr webhooks: with user scrape caching on, new imports get the right artwork within about a minute of landing, instead of waiting for the next scheduled run.
- Auto-managed bulk files: let the app add, label and sort URLs for you.

**Kometa**
- Reset Kometa's overlay label on upload so overlays get reapplied, or save artwork straight to your Kometa asset directory and let Kometa do the applying. See [Kometa integration](#kometa-integration).

## Installation

### Docker (recommended)

There's a ready-to-run image on the GitHub Container Registry. Create a folder for the app, drop this in as `docker-compose.yml` (or download and rename [docker-compose.example.yml](docker-compose.example.yml)), and customise your [time zone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) and paths:

```yaml
services:
  artwork_uploader:
    image: ghcr.io/mscodemonkey/artwork-uploader:latest
    container_name: artwork-uploader
    ports:
      - "4567:4567"
    volumes:
      - ./bulk_imports:/artwork-uploader/bulk_imports:rw
      - ./config:/artwork-uploader/config:rw
      - <HOST_PATH_TO_KOMETA_ASSET_DIRECTORY>:/assets:rw # Optional, only if you save assets to your Kometa asset directory
      - <HOST_TEMP_PATH>:/temp:rw # Optional, only for testing with a temp dir
    environment:
      - TZ=Europe/London
      - RUNNING_IN_DOCKER=1
    restart: unless-stopped
```

Then:

```bash
docker compose up -d
```

Open `http://your_ip_address:4567` in a browser and you're ready to rock and roll!

### Unraid

The Docker image runs happily on Unraid. Add a container pointing at `ghcr.io/mscodemonkey/artwork-uploader:latest`, map port `4567`, and map two paths: `/artwork-uploader/config` for the config and `/artwork-uploader/bulk_imports` for your bulk files (plus `/assets` if you use the Kometa asset directory). Set the `RUNNING_IN_DOCKER=1` environment variable. Community Applications support is being worked on in [#43](https://github.com/mscodemonkey/artwork-uploader-plex/issues/43).

### From source

You'll need [Python](https://www.python.org/downloads/) 3.12 or later.

```bash
# Clone the repository (or download and extract the Zip)
git clone https://github.com/mscodemonkey/artwork-uploader-plex.git
cd artwork-uploader-plex

# Create and activate a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# Install the dependencies
pip install -r requirements.txt

# Run it
python artwork_uploader.py
```

With no arguments, Artwork Uploader starts a web server on port 4567 (this may change!). If you get dependency errors, you're probably not using the virtual environment. See [Troubleshooting](#troubleshooting).

## Configuration

Configuration lives in `config/config.json`. You can rename `example_config.json` to `config.json` before first run, or just start the app: it creates one and prompts you to edit it. Almost everything can also be changed from the Settings tab in the web UI.

### Connecting to Plex

`"base_url"`
- The IP address (and port) of your Plex server, e.g. `http://12.34.56.78:32400/`, or `https://myplex.example.com` if behind a reverse proxy like Nginx or Caddy.

`"token"`
- Your Plex token ([how to find it](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)).

`"tv_library"`
- The name of your TV Shows library (e.g. `"TV Shows"`). For multiple libraries, use an array:

```json
"tv_library": ["TV Shows", "Kids TV Shows"],
"movie_library": ["Movies", "Kids Movies"]
```

Artwork is applied to the same media in every listed library.

`"movie_library"`
- The name of your Movies library (e.g. `"Movies"`). Arrays work here too, as above.

### Artwork selection

`"mediux_filters"` and `"tpdb_filters"`
- Which artwork types to upload, per provider. Anything not listed is skipped unless requested per URL. The options:
  - `show_cover`, `background`, `square_art`, `season_cover`, `title_card`, `movie_poster`, `collection_poster`
- ThePosterDB does not provide title cards, backgrounds or square art, so those filters are not available for it in the web UI.
- Global filters can be overridden per URL: on the command line with `--filters`, after the URL in a bulk file, or with the checkboxes in the web UI's scraper tab.

**A note on square art:** MediUX supports per-season square art for TV shows, but Plex only supports one square art asset at the show level. When saving to the Kometa asset directory, the first asset processed is saved as `square.ext` and applied by Kometa; the rest are saved as `square_alt_#.ext` so you can rename an alternative into place. When applying directly to Plex, the first one is applied and the rest are ignored.

### Artwork behaviour

`"track_artwork_ids"`
- `true` (recommended) stores an artwork ID in a Plex label per item, so re-runs skip artwork that hasn't changed and finish fast. `false` uploads everything every run, like `--force` on every item, which can mean long run times, especially on ThePosterDB. Leave it `true` and use `--force` when you need to!

`"skip_locked_artwork"`
- `true` skips any artwork whose target field (poster, background or square art) is locked in Plex, unless `--force` is used. Plex locks a field whenever artwork is deliberately set, manually or by an upload, so this makes scheduled runs fill items still on default artwork while leaving your curation alone. `false` (the default) applies artwork regardless of locks.

`"allow_artist_updates"`
- ThePosterDB only. `true` lets a run replace artwork it applied earlier when the same artist has posted a newer version, even though the field is locked. Artwork you set by hand (anything without an artwork-ID label) and artwork from a different artist are left alone, and it only ever moves forward to a newer upload, so runs settle on each artist's latest rather than flip-flopping. Requires both `skip_locked_artwork` and `track_artwork_ids`. Because this overwrites artwork the tool chose earlier, note your current posters before the first run if you want to be able to revert.

### Scraping and caching

`"cache_user_scrapes"`
- ThePosterDB only. `true` keeps a local index of each user's uploads (a small SQLite file in your config directory), so scraping a user again only fetches pages until it reaches uploads it has already seen. Full-catalogue re-runs drop from hundreds of page requests to a couple, which is also much kinder to ThePosterDB. `false` (the default) crawls every page on every user scrape.

`"user_cache_refresh_days"`
- Days between full re-crawls of a cached user, to pick up edited or deleted uploads (default `7`). Only used when `cache_user_scrapes` is `true`.

`"local_library_matching"`
- ThePosterDB only. `true` (the default) matches scraped artwork against your Plex libraries locally before fetching each poster's page, so big user scrapes skip everything you don't own without a web request. Matching is by title rather than TMDb ID (ThePosterDB doesn't provide the ID on the set page), so it's much faster but less accurate for foreign titles or titles with special characters. The poster page is still checked right before anything is uploaded, so nothing less accurate is ever written. Set to `false` if items you own start logging "not available on Plex" because their Plex titles differ from ThePosterDB's.

### Kometa

`"reset_overlay"`
- `true` removes the Overlay label that Kometa uses when we upload new artwork, so Kometa reapplies overlays on its next run. `false` leaves the label alone and Kometa will not reapply overlays.

`"save_to_kometa"`
- `true` saves scraped artwork to the Kometa asset directory instead of applying it to Plex. `false` keeps the default behaviour of applying artwork to Plex directly. See [Kometa integration](#kometa-integration).

`"kometa_base"`
- Path to your Kometa base asset directory.

`"temp_dir"`
- Optional. A temporary save directory used with the `--temp` argument (or the corresponding web UI toggle) for testing.

`"stage_assets"`
- `true` downloads assets for TV seasons and episodes not yet in Plex, useful when a scheduled run happens before your automation has downloaded a new season. Does not apply to the Specials season (Season 0).

### Bulk files

`"auto_manage_bulk_files"`
- `true` automatically adds, labels and sorts URLs from the scrape tab into the currently loaded bulk import file. It won't auto-save yet, but that might come later. `false` leaves your bulk files up to you.

### Notifications

`"apprise_urls"`
- A list of notification channels, each an object with an Apprise service URL and the events it should hear about, e.g. `{"url": "discord://...", "events": ["run_completed", "run_completed_with_errors"]}`. Valid events: `run_completed`, `run_completed_with_errors`, `run_failed_to_start`, `run_skipped`, `run_cancelled`. See [the Apprise service list](https://appriseit.com/services/) for how to build a URL for your favourite service.

### Webhooks

`"enable_webhooks"`
- ThePosterDB only. `true` enables the Sonarr/Radarr import webhook endpoints (`/webhook/radarr` and `/webhook/sonarr`). `false` (the default) leaves them disabled and returning 404. Requires `cache_user_scrapes`, so there is an index to look artwork up in.

`"webhook_token"`
- The shared secret webhook requests must provide: in an `X-Webhook-Token` header, as the HTTP Basic password, or as a `?token=` query parameter. Required when `enable_webhooks` is `true`.

`"webhook_tpdb_users"`
- ThePosterDB user names to apply cached artwork from on import, in order of preference (first match wins). Only used when `enable_webhooks` is `true`.

`"webhook_apply_delay"`
- Seconds to wait after an import before applying artwork (default `30`). The *arr apps fire the webhook the moment they import a file, usually before Plex has scanned it, so this gives Plex a head start. If the item still isn't in Plex, the apply retries for a few minutes before giving up.

### Timeouts and retries

`"plex_connect_timeout"`
- Timeout in seconds for connecting to or uploading artwork to Plex (default `10`).

`"kometa_download_timeout"`
- Timeout in seconds for downloading assets from ThePosterDB or MediUX (default `10`).

`"upload_retry_attempts"`
- Total number of times to attempt an operation, including the original attempt (default `3`). Only transient errors (timeouts or server errors) are retried.

`"upload_retry_backoff_seconds"`
- Cool-down before the first retry (default `1`). Doubles on every subsequent retry.

## Usage

### Web UI

The web UI is a full interface for the app: configure any setting, launch scrapes, run bulk imports, upload Zip files and watch the log and run history. It supports multiple browser instances against the same server, keeps every instance updated on the state of a running operation, guards against launching two scrapes at once, and lets you cancel an operation that's taking too long. There's a debug mode too, in case you run into issues and want to open a GitHub issue for our inspection.

It's fully responsive, so it works just as well from your phone. See [Screenshots](#screenshots).

### Command line

Point it at a single set or boxset:

```bash
python artwork_uploader.py https://mediux.pro/sets/9242

# Or a boxset (a collection of multiple sets)
python artwork_uploader.py https://mediux.pro/boxsets/1153
```

Depending on your environment you may need `python3` instead of `python`.

#### Optional command line arguments

`--add-sets` also parses any additional sets on the page (ThePosterDB).

`--add-posters` also parses the additional posters section of the set (ThePosterDB).

`--force` forces artwork to be updated even if it's the same as what's on Plex already. Or maybe you changed the artwork manually and want to override it...

`--skip-locked` skips any artwork whose target field is locked in Plex (i.e. it's been deliberately set, manually or by a previous upload), unless `--force` is also used. Same as `skip_locked_artwork` in `config.json`, but per URL.

`--allow-artist-updates` lets a run replace artwork it applied earlier when the same artist has posted a newer version, while still leaving hand-set artwork and other artists' artwork alone. Same as `allow_artist_updates` in `config.json`, but per URL. Needs `--skip-locked` (or `skip_locked_artwork`) and `track_artwork_ids` to take effect.

`--exclude <id1> [<id2> <id3> ...]` excludes the poster or artwork with the given ID. Grab the ID from the session log: ThePosterDB IDs are numbers, MediUX IDs are UUIDs. For TV shows you can also exclude specific episodes or whole seasons, and mix them with artwork IDs:
- `--exclude s01e05` excludes the title card for season 1 episode 5
- `--exclude s1e5` is the same (both formats work)
- `--exclude s02` excludes the season cover and every episode title card for season 2
- `--exclude s00e01 s02` excludes specials episode 1 and all of season 2

`--filters <filter1> [<filter2> ...]` uploads **only** the listed artwork types: `show_cover`, `background`, `square_art`, `season_cover`, `title_card`, `movie_poster`, `collection_poster`.

`--year <year>` overrides the year to look for in Plex. Sometimes the year on MediUX or ThePosterDB doesn't match the year in Plex, so the artwork won't apply. Ignored in bulk mode, where you specify it per line.

`--kometa` saves artwork to your Kometa asset directory instead of applying it to Plex. Not needed if `save_to_kometa` is `true` in `config.json`. Existing assets in the directory are not overwritten unless `--force` is also given.

`--temp` saves artwork to the temporary directory (`temp_dir` in `config.json`) instead of the Kometa asset directory, for testing.

`--stage`, together with `--kometa` (or `save_to_kometa`), downloads assets for TV seasons and episodes not yet in Plex. Not needed if `stage_assets` is `true` in `config.json`. Does not apply to the Specials season (Season 0).

`--no-cache` crawls every page of a ThePosterDB user this run, ignoring the cached index (the index is still refreshed). Handy for forcing a full refresh of one user when `cache_user_scrapes` is enabled.

All of these options also work in the web UI's scraper tab and in bulk files: just add them after the URL, e.g.

```
https://theposterdb.com/set/71510 --add-posters --force
```

### Bulk files

Import multiple links from a .txt file with the bulk argument:

```bash
python artwork_uploader.py bulk bulk_import.txt
```

- One URL per line, with any of the options above after it. Lines starting with `#` or `//` are ignored as comments.
- With no file argument, the default from `bulk_txt` in `config.json` is used.
- Enable `auto_manage_bulk_files` and the app will add, label and sort URLs from the scrape tab into the open bulk file for you.

### Scheduler and notifications

The scheduler lets you leave the app running and keep your artwork up to date automatically. On the bulk imports page, click the clock to add, edit or remove schedules for the open file. A file can carry more than one schedule, and each one either runs daily at a fixed time or repeats every N hours or days, so a large nightly run and a smaller twice-a-day one can share the same list. Missed schedules are caught up when the app comes back, for both daily and interval schedules.

A few settings make scheduled runs much more pleasant:

- `cache_user_scrapes`: scheduled user scrapes only fetch uploads that are new since the last run.
- `skip_locked_artwork`: scheduled runs only fill items still on default artwork, so it's safe to leave running against a curated library.
- `allow_artist_updates`: scheduled runs may also move artwork forward to an artist's newer version. See [Artwork behaviour](#artwork-behaviour) for the guard rails.

You can also configure push notifications for scheduled runs through [Apprise](https://appriseit.com/services/). Each channel is switched on or off per event from the web UI: a run completing cleanly, completing with errors, failing to start, being skipped, or being cancelled. New channels default to the two completion events; opt each channel in to the noisier ones yourself. Manual runs stay silent unless you tick "Notify" before starting one. Scheduled runs always attempt to notify, subject to each channel's event selection.

### Automatic artwork for new imports (Sonarr/Radarr webhook)

With `cache_user_scrapes` enabled (ThePosterDB only), the app already knows every poster your favourite users have uploaded, so it can apply the right artwork within about a minute of Sonarr or Radarr importing something, instead of waiting for the next scheduled run.

Turn on `enable_webhooks`, set a `webhook_token`, and list the ThePosterDB users to apply from (in order of preference) under Webhook settings in the web UI. Then add a webhook connection in each app:

- **Radarr / Sonarr:** Settings → Connect → + → Webhook. URL `http://<artwork-uploader-host>:4567/webhook/radarr` (or `/webhook/sonarr`), method POST. Tick only the "On File Import" trigger. Send the token as the connection's password, or as a header: click the **Advanced** (cog) button and add a header with key `X-Webhook-Token` and the token as the value. The Test button is acknowledged so you can save the connection.

On an import, the title is looked up in the cached index. If one of your configured users covers it, that single poster (plus season covers for the imported seasons on TV items) is applied through the same processing path as a normal scrape, so artwork labels, locked-artwork skips and Kometa asset mode all behave the same. Imports can reach the webhook before Plex has scanned the new file, so the apply retries for a few minutes, then leaves it to the next scheduled run. Ambiguous title matches (same-name remakes, for example) are skipped rather than guessed, and nothing is applied when no configured user has the title. The endpoints return 404 while `enable_webhooks` is off.

### Kometa integration

Kometa support comes in two flavours:

1. **Overlay reset** (the simple one): set `reset_overlay` to `true` and the app removes Kometa's overlay label when it uploads new artwork, so the next Kometa run reapplies the overlay.
2. **Asset directory mode**: set `save_to_kometa` to `true` (or tick the option in the web UI) and artwork is saved to Kometa's [asset directory](https://kometa.wiki/en/latest/kometa/guides/assets/) instead of being applied to Plex. Whenever Kometa next runs, it applies all new or updated artwork with its overlays. Set `kometa_base` to your base asset directory.

Asset directory mode assumes:

- `asset_folders` is `true` in Kometa's config.yml, so each show or movie has its own folder
- `assets_for_all` is `true` in each library
- `assets_for_all_collections` is `true` in each library, if you want collection assets managed
- `create_asset_folders` is `true`
- Each library has a folder matching the library name under the base asset directory
- Collections keep their assets in the same folders as the movies or shows of the same library

<details>
<summary>Example Kometa config.yml snippet</summary>

```yaml
libraries:                           # This is called out once within the config.yml file
  Movies:                            # These are names of libraries in your Plex
    settings:
      asset_directory:
        - config/assets/Movies
      create_asset_folders: true
    operations:
      assets_for_all: true
      assets_for_all_collections: true
  [...]

  TV Shows:
    settings:
      asset_directory:
        - config/assets/TV Shows
      create_asset_folders: true
    operations:
      assets_for_all: true
      assets_for_all_collections: true
   [...]

settings:
  [...]
  asset_directory:
  - config/assets
  asset_folders: true
  asset_depth: 2
  create_asset_folders: true
  [...]
```

</details>

<details>
<summary>Example asset directory structure</summary>

```
  path/to/base/asset/directory
  ├── Movies
  │   ├── Death in Venice (1971)
  │   │   ├── poster.jpg
  │   │   └── background.jpg
  │   ├── Die Another Day (2002)
  │   │   ├── poster.jpg
  │   │   └── square.png
  │   ├── Spy Kids Collection
  ·   ·   ├── poster.jpg
  ·   ·   └── background.png
  │   └── The Amazing Spider-Man (2012)
  │       └── background.jpg
  ├── Movies 4K
  │   ├── 10 Cloverfield Lane (2016)
  │   │   ├── poster.jpg
  │   │   └── background.png
  │   ├── 28 Weeks Later (2007)
  │   │   └── poster.png
  ·   ·
  ·   ·
  │   └── Zootopia (2016)
  │       └── poster.jpg
  ├── TV Shows
  │   ├── Ted Lasso (2020) {tmdb-97546}
  │   │   ├── poster.png
  │   │   ├── square.webp
  │   │   ├── Season01.jpg
  │   │   ├── Season02.jpg
  │   │   ├── Season03.jpg
  │   │   ├── S01E01.jpg
  │   │   ├── S01E02.jpg
  │   ·   ·
  │   ·   ·
  │   │   └── S03E12.jpg
  ·   ·
  ·   ·
  │   └── Alien - Earth
  │       ├── poster.jpg
  │   │   ├── square.jpeg
  │       └── background.png
  └── TV Shows 4K
      ├── Foundation (2021)
      │   ├── poster.png
      │   ├── Season01.jpg
      │   ├── Season02.jpg
      ·   ├── Season03.jpg
      ·   └── background.png
      │
      └── Tales From The Loop
          ├── poster.png
          └── background.png

```

</details>

Finally, if you're using the asset directory and running in Docker, the app detects it (via the `RUNNING_IN_DOCKER` environment variable) and hardcodes the Kometa base directory to `/assets` and the temp directory to `/temp`. Map your real asset and temp folders to those paths in the container, as in the [Docker compose example](#docker-recommended). Your real paths stay in `config.json`, so running the app outside the container still works too.

## Screenshots

![Scraper](assets/ScraperTab.png)

<details>
<summary>More desktop screenshots</summary>

![Bulk Import](assets/BulkImportTab.png)
![Upload ZIP](assets/UploaderTab.png)
![Settings](assets/SettingsTab.png)
![Log](assets/LogTab.png)
![History](assets/HistoryTab.png)
![About](assets/AboutTab.png)

</details>

And a responsive mobile UI, perfected for using the app from your smartphone!

<details>
<summary>Mobile screenshots</summary>

![Mobile Scraper](assets/ScraperMobile.jpeg)
![Mobile Bulk Import](assets/BulkImportMobile.jpeg)
![Mobile Bulk Import while Running](assets/BulkImportRunningMobile.jpeg)
![Mobile Uploader](assets/UploaderMobile.jpeg)
![Mobile Settings](assets/SettingsMobile.jpeg)
![Mobile Log](assets/LogMobile.jpeg)
![Mobile History](assets/HistoryMobile.jpeg)
![Mobile About](assets/AboutMobile.jpeg)

</details>

## Troubleshooting

### "Required dependencies are missing or incompatible"

Python packages can't be imported. Common causes:

1. **Requirements not installed**
   ```bash
   pip install -r requirements.txt
   # or
   python3 -m pip install -r requirements.txt
   ```

2. **Wrong Python version.** Artwork Uploader requires Python 3.12 or later:
   ```bash
   python3 --version
   ```

3. **Architecture mismatch (Apple Silicon Macs).** If you're on an M-series Mac and see errors about "incompatible architecture (have 'x86_64', need 'arm64')", your packages were compiled for Intel. Reinstall them for ARM64:
   ```bash
   pip3 uninstall Pillow Flask flask-socketio eventlet cffi cryptography -y
   pip3 install Pillow Flask flask-socketio eventlet cffi cryptography
   ```

4. **Not using the virtual environment.** If you created a `.venv` but still get import errors, you're likely running system Python:
   ```bash
   # Wrong - uses system Python ❌
   python3 artwork_uploader.py

   # Right - activate first, then run ✅
   source .venv/bin/activate
   python artwork_uploader.py

   # Alternative - run directly from venv ✅
   .venv/bin/python artwork_uploader.py
   ```

### "Cannot access localhost:4567" or "Server won't start"

If you see the scheduler messages but can't access the web UI:

1. **Check you're using the virtual environment** (see above).
2. **Check whether another process is using port 4567**:
   ```bash
   lsof -i :4567
   # If something is using it, either kill it or change the port in config.json
   ```
3. **Try the other local URLs**: `http://localhost:4567`, `http://127.0.0.1:4567`, `http://0.0.0.0:4567`.
4. **Check firewall settings** to make sure port 4567 isn't blocked.

### Strange "400 Bad request" errors in logs with binary data

Errors like this in your logs:

```
127.0.0.1 - - [13/Oct/2025 12:21:30] code 400, message Bad request version ('\x16\x03\x01...')
```

**This is completely normal and harmless!** They're TLS/SSL handshake attempts: something (your browser, an extension, or a security tool) is trying to connect over HTTPS to the HTTP-only Flask server, and Flask correctly rejects it. If you want HTTPS, put a reverse proxy like Nginx or Caddy in front.

### Plex connection issues

**"Cannot reach Plex server" or the application hangs on startup**

The app has a 3-second timeout for Plex connections and shows a clear error if it can't connect:

```
======================================================================
WARNING: Could not connect to Plex TV libraries
======================================================================
Cannot reach Plex server at http://192.168.1.4:32400. Please check
that the server is running and the address is correct.

The web UI will still start, but you won't be able to upload artwork
until you fix the Plex connection in Settings.
```

How to fix:

1. **Verify Plex is running.**
2. **Test connectivity manually**:
   ```bash
   curl http://your-plex-ip:32400
   # Should return some XML if Plex is accessible
   ```
3. **Check the IP address.** Your Plex server IP might have changed: Plex Web App → Settings → Network → Show Advanced.
4. **Update config.json**:
   ```json
   {
     "base_url": "http://192.168.1.100:32400",
     "token": "your-plex-token"
   }
   ```
5. **Firewall/network:** make sure port 32400 isn't blocked.

**"Invalid Plex token or base URL"**
- Verify your Plex token in `config.json` ([finding your Plex token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)).
- The base URL must include the protocol and port, e.g. `http://192.168.1.100:32400`.

**"Library not found"**
- Library names in the config must match Plex exactly (case-sensitive), and the library type (TV vs Movie) must match too.

### Scraping issues

**"Can't scrape URL"**
- Verify the URL is from a supported source (ThePosterDB or MediUX).
- Check your internet connection.
- Some scrapers may be rate-limited. Wait a few minutes and try again.

### Performance issues

**Slow upload speeds**
- ThePosterDB has a 6-second rate limit between requests.
- Use `--filters` to only upload the artwork types you want.
- Enable `track_artwork_ids` so already-uploaded artwork is skipped.

## For developers

If you'd like to contribute or want to understand how it works under the hood, start with the [Technical Information for Contributors](TECHNICAL_INFO.md): architecture overview, service layer documentation, how to add features, testing procedures and code style guidelines.

## Thanks

Many thanks to Brian Brown ([@bbrown430](https://github.com/bbrown430)) for the original plex-poster-set-helper - what a fantastic idea! It's saved me a load of time, and it's made my Plex beautiful! And it's made me learn a bit of Python too! I really hope you don't mind me taking your work and running with it, please get in touch if you'd like to merge the two projects!

## Disclaimer

This started as a first Python project and it's still how I learn, so it will keep changing and I can't offer support beyond my own knowledge, or any guarantee that it will actually work! Any help would be appreciated, so feel free to contribute. I'm also aware that scraping breaks ThePosterDB's terms of service, so please consider using their Zip download with the upload feature instead. Wish these sites had APIs!
