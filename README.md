
# plex-poster-set-helper

plex-poster-set-helper is a tool to help upload sets of posters from ThePosterDB or MediUX to your Plex server in seconds!

## What's different in this fork?
My update will store the poster ID in a Plex label against each movie or collection, so it can check whether the same artwork is about to be uploaded again.  If it detects the same artwork has been requested, it'll skip it, resulting in a quicker run time.  If you really want to upload it again, use the --force option at the command line, in the bulk file, or when entering the URL in the GUI.

There are also a couple of new options for thePosterDb, which will allow you to also grab additional sets and additional posters from the same page.  This is sometimes useful for big sets like the Marvel or Disney movies, where you'll otherwise need to specify multiple sets.

## Why did I fork it?
Because i've never coded in Python before so am using it to learn at the same time.  I'm sure my code is probably a bit scrappy at the moment!

## Thanks
Many thanks to Brian Brown [@bbrown430] (https://github.com/bbrown430) for this fantastic utility.  It's saved me a load of time and it's made my Plex beautiful!


## Installation

1. [Install Python](https://www.python.org/downloads/) (if not installed already)

2. Extract all files into a folder

3. Open a terminal in the folder

4. Install the required dependencies using

   ```bash
   pip install -r requirements.txt
   ```

5. Rename example_config.json to config.json, and populate with the proper information:
   - **"base_url"**  
     - The IP and port of your Plex server. e.g. "http://12.345.67.890:32400/".
   - **"token"**  
     - Your Plex token (can be found [here](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)).
   - **"tv_library"**  
     - The name of your TV Shows library (e.g., "TV Shows"). Multiple libraries are also supported (see the **Multiple Libraries** section below).
   - **"movie_library"**  
     - The name of your Movies library (e.g., "Movies"). Multiple libraries are also supported (see the **Multiple Libraries** section below).
   - **"mediux_filters"**  
     - Specify which media types to upload by including these flags:
       - show_cover
       - background
       - season_cover
       - title_card

## Usage

Run python plex_poster_set_helper.py in a terminal, using one of the following options:

### Command Line Arguments

The script supports various command-line arguments for flexible use.

1. **Launch the GUI**  
   Use the gui argument to open the graphical user interface:
   
   ```bash
   python plex_poster_set_helper.py gui
   ```

2. **Single Link Import**  
   Provide a link directly to set posters from a single MediUX or ThePosterDB set:
   
```bash
   python plex_poster_set_helper.py https://mediux.pro/sets/9242
   ```
   **Additional command line arguments**
   - ```**--add-sets**``` will also parse any additional sets when using the Poster DB 
   - **--add-posters** will also parse the additional posters section of the set, when using the Poster DB
   - **--force** will force the artwork to be updated even if it's the same as the one on plex already - or maybe you changed the artwork manually and want to override it...
   - **--filters** will only apply the selected media types, based on the options below
     - show_cover
     - background
     - season_cover
     - title_card 
     - movie_poster
     - collection_poster
   - **--year** override the year that it will look for in Plex.  Sometimes the year in Mediux or TPDb doesn't match the year of the show or movie in Plex, therefore won't update the artwork.  Use this option with the year in Plex to force a match.

   These options can also be used in the URL scraper GUI, and in your bulk file, just add them straight after the URL in each line, for example 
   ```
   https://theposterdb.com/set/71510 --add_posters --force
   ```

4. **Bulk Import**  
   Import multiple links from a .txt file using the bulk argument:
   
   ```bash
   python plex_poster_set_helper.py bulk bulk_import.txt
   ```

   - The .txt file should contain one URL per line. Lines starting with # or // will be ignored as comments.

   - **If no text file parameter is provided, it will use the default value from config.json for bulk_txt.**


## Supported Features

### Interactive CLI Mode

![GUI Overview](https://raw.githubusercontent.com/tonywied17/plex-poster-set-helper/refs/heads/main/assets/cli_overview.png)

If no command-line arguments are provided, the script will enter an interactive CLI mode, where you can select from menu options to perform various tasks:

- **Option 1:** Enter a ThePosterDB set URL, MediUX set URL, or ThePosterDB user URL to set posters for individual items or entire user collections.
- **Option 2:** Run a bulk import by specifying the path to a `.txt` file containing multiple URLs (or simply press `Enter` to use the default bulk file defined in `config.json`).
- **Option 3:** Launch the GUI for a graphical interface.
- **Option 4:** Stop the program and exit.

When using bulk import, if no file path is specified, the script will default to the file provided in the `config.json` under the `bulk_txt` key. Each URL in the `.txt` file should be on a separate line, and any lines starting with `#` or `//` will be ignored as comments.

### GUI Mode

![GUI Overview](https://raw.githubusercontent.com/tonywied17/plex-poster-set-helper/refs/heads/main/assets/gui_overview.png)
![Bulk Import](https://raw.githubusercontent.com/tonywied17/plex-poster-set-helper/refs/heads/main/assets/bulk_import.png)
![URL Scrape](https://raw.githubusercontent.com/tonywied17/plex-poster-set-helper/refs/heads/main/assets/url_scrape.png)


The GUI provides a more user-friendly interface for managing poster uploads. Users can run the script with python plex_poster_set_helper.py gui to launch the CustomTkinter-based interface, where they can:
- Easily enter single or bulk URLs.
- View progress, status updates, and more in an intuitive layout.

### Multiple Libraries

To target multiple Plex libraries, modify config.json as follows:

```json
"tv_library": ["TV Shows", "Kids TV Shows"],
"movie_library": ["Movies", "Kids Movies"]
```

Using these options, the tool will apply posters to the same media in all specified libraries.

### Bulk Import

1. Use the bulk argument to import your default `bulk_text` file specified in `config.json`.
2. Or, specify the path to a .txt file containing URLs as a second argument. Each URL will be processed to set posters for the corresponding media.

### Filters

The mediux_filters option in config.json allows you to control which media types get posters:
- show_cover: Upload covers for TV shows.
- background: Upload background images.
- season_cover: Set posters for each season.
- title_card: Add title cards.

## Executable Build

In the `dist/` directory, you'll find the compiled executable for Windows: `Plex Poster Set Helper.zip`. This executable allows you to run the tool without needing to have Python installed.

To rebuild the executable:

*Note: Prior to building, set the `interactive_cli` boolean to False on line `20` to ensure the executable launches in GUI Mode by default*

1. Install PyInstaller if you don't have it already:
   ```bash
   pip install pyinstaller
   ```

2. Use the provided spec file (`_PlexPosterSetHelper.spec`) to build the executable:

   ```bash
   pyinstaller _PlexPosterSetHelper.spec
   ```

This will create the executable along with the necessary files.
