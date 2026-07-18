"""
Service for coordinating artwork scraping and uploading.

This service handles the business logic of scraping artwork and processing
it for upload to Plex, separating it from UI/notification concerns.
"""

import os
import time
from typing import Optional, Callable, Tuple

from scrapers.scraper import Scraper
from processors.upload_processor import UploadProcessor
from plex.plex_connector import PlexConnector
from models.options import Options
from models.callbacks import ProcessingCallbacks
from utils.utils import elapsed_time
from core import globals
from core.exceptions import (
    PlexConnectorException,
    ScraperException,
    CollectionNotFound,
    MovieNotFound,
    ShowNotFound,
    NotProcessedByFilter,
    NotProcessedByExclusion
)

class ArtworkProcessor:
    """Coordinates scraping and uploading of artwork."""

    def __init__(self, plex: PlexConnector, callbacks: Optional[ProcessingCallbacks]) -> None:
        self.plex = plex
        self.callbacks = callbacks

    def scrape_and_process(
        self,
        url: str,
        bulk: bool,
        options: Options,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Scrape artwork from a URL and process it for upload to Plex.

        Args:
            url: URL to scrape
            options: Processing options
            callbacks: Optional callbacks for UI updates

        Returns:
            Title of the scraped content, or None if no title found

        Raises:
            PlexConnectorException: If Plex connection fails
            ScraperException: If scraping fails
        """
        # Check Plex connection
        try:
            self.plex.connect()
        except PlexConnectorException as e:
            self.callbacks.log(f"❌ Plex connection error: {str(e)}")
            raise PlexConnectorException(f"Plex connection error: {str(e)}") from e

        # Scrape the artwork
        scraper = Scraper(url=url, callbacks=self.callbacks)
        scraper.set_options(options)

        try:
            if "/boxsets/" in url:
                pass #self.callbacks.status(f"Scraping MediUX Boxset from {url}, this may take a while...", "info", True, True)
            else:
                pass #self.callbacks.status(f"Scraping {url}", "info", True, True)
            start_time = time.time()
            scraper.scrape()
        except ScraperException as e:
            self.callbacks.log(f"❌ Scraper error: {str(e)}")
            raise ScraperException(f"Scraper error: {str(e)}") from e

        # Process the scraped artwork
        processor = UploadProcessor(self.plex)
        processor.set_options(options)

        description = f"TBDb portfolio • {scraper.author}" if "/user" in url else f"{scraper.title} • {scraper.author}"

        self.callbacks.progress(0, 0, description, "main")

        self.callbacks.log(f"🔍 {description} | Fetched {scraper.total} asset(s) from {f"ThePosterDB" if scraper.source == "theposterdb" else "MediUX"}")
        if scraper.errored > 0:
            self.callbacks.log(f"⚠️ {description} | Encountered errors scraping {scraper.errored} asset(s) from {f"ThePosterDB" if scraper.source == "theposterdb" else "MediUX"}")
        if scraper.skipped > 0:
            self.callbacks.log(f"⏩ {description} | Skipping {scraper.skipped} asset(s) based on exclusions ({scraper.exclusions}), filters ({scraper.filtered}) or errors ({scraper.errored}). Processing {scraper.total - scraper.skipped} asset(s).")

        if scraper.total - scraper.skipped == 0:
            self.callbacks.progress(1, 1, f"{description} • All assets skipped", "main")
        
        # Process collections
        n = 1
        title = f"for {scraper.title}" if scraper.title else ""
        for artwork in scraper.collection_artwork:
            if globals.cancel_scrape:
                break
            self.callbacks.progress(n, scraper.total - scraper.skipped, f"{description} • {n} of {scraper.total - scraper.skipped}", "main")
            n += 1
            self._process_single_artwork(
                artwork,
                processor.process_collection_artwork
            )

        # Process movies
        for artwork in scraper.movie_artwork:
            if globals.cancel_scrape:
                break
            self.callbacks.progress(n, scraper.total - scraper.skipped, f"{description} • {n} of {scraper.total - scraper.skipped}", "main")
            n += 1
            self._process_single_artwork(
                artwork,
                processor.process_movie_artwork
            )

        # Process TV shows
        for artwork in scraper.tv_artwork:
            if globals.cancel_scrape:
                break
            self.callbacks.progress(n, scraper.total - scraper.skipped, f"{description} • {n} of {scraper.total - scraper.skipped}", "main")
            n += 1
            self._process_single_artwork(
                artwork,
                processor.process_tv_artwork
            )

        end_time = time.time()
        elapsed = elapsed_time(end_time - start_time)
        if globals.cancel_scrape:
            self.callbacks.progress(1, 1, "", "main")  # nudge to 100% so the frontend clears the bar (it only hides at 100%)
            self.callbacks.log(f"🛑 {description} | Stopped by user • {self.callbacks.success_counter[0]} asset(s) updated before stopping")
            if not bulk:
                self.callbacks.status(f"Stopped artwork {title} by {scraper.author}", "warning")
        else:
            self.callbacks.assets(count=(scraper.total - scraper.skipped))
            self.callbacks.log(f"✔️ {description} | {scraper.total - scraper.skipped} asset(s) processed in {elapsed} • {self.callbacks.success_counter[0]} asset(s) updated")
            if not bulk:
                self.callbacks.status(f"Processed all artwork {title} by {scraper.author}", "success")
        return scraper.title, scraper.author

    def _process_single_artwork(
        self,
        artwork: dict,
        process_func: Callable[[dict], str],
    ) -> None:
        """
        Process a single piece of artwork with error handling.

        Args:
            artwork: Artwork dictionary
            process_func: Function to process the artwork (from UploadProcessor)
            callbacks: Optional callbacks for UI updates
        """
        try:
            # Process the artwork
            results = process_func(artwork)

            for result in results:
            # Track successful uploads (those starting with ✅ or ♻️)
                if result.startswith('✅') or result.startswith('♻️'):
                    self.callbacks.success(1)

            # Log the result
                self.callbacks.log(result)

        except CollectionNotFound as e:
            self.callbacks.log(f"⚠️ {str(e)}")

        except MovieNotFound as e:
            self.callbacks.log(f"⚠️ {str(e)}")

        except ShowNotFound as e:
            self.callbacks.log(f"⚠️ {str(e)}")

        except ScraperException as e:
            self.callbacks.log(f"❌ {str(e)}")
            self.callbacks.debug(f"ScraperException: {str(e)}")

        except PlexConnectorException as e:
            self.callbacks.log(f"❌ {str(e)}")
            self.callbacks.debug(f"PlexConnectorException: {str(e)}")

        except Exception as e:
            self.callbacks.log(f"❌ {str(e)}")
            self.callbacks.debug(f"Error processing {artwork["title"]} ({artwork["year"]}):{str(e)}")
            self.callbacks.status(
                f"Error: {str(e)}",
                "danger",
                False,  # no spinner
                False   # not sticky
            )

    def process_uploaded_files(
        self,
        file_list: list[dict],
        skipped: int,
        zip_title: Optional[str],
        zip_author: Optional[str],
        zip_source: Optional[str],
        options: Options,
        override_title: Optional[str] = None
    ) -> None:
        """
        Process a list of uploaded artwork files.

        Args:
            file_list: List of artwork dictionaries with 'media', 'title', etc.
            options: Processing options
            callbacks: Optional callbacks for UI updates
            override_title: Optional title to override in all files
        """
        processor = UploadProcessor(self.plex)
        processor.set_options(options)

        total_files = len(file_list)
        title = override_title if override_title else zip_title if zip_title else "Unknown"
        author = zip_author if zip_author else "Unknown"
        source = zip_source if zip_source else "Unknown"

        if total_files > 0:
            # ZIP file titles don't contain year info, even for ZIPs of single movies or TV shows
            # In that case, we try to infer the year from the first file's metadata
            # We determine if it's a single movie/TV ZIP by checking if the title of the ZIP file is part of the title of the first file
            # Otherwise we assume it's a ZIP file containing artwork for multiple shows/movies/collections and leave year as None
            year = file_list[0].get('year', 'unknown') if title in file_list[0].get('title', 'unknown') else None
            self.callbacks.debug(f"Processing {total_files} files from {source} ZIP file for {title}{f' ({year})' if year else ''}")
        else:
            year = None
            self.callbacks.debug("No files to process in uploaded ZIP file")
        
        success_counter = 0  # Mutable counter to track successful uploads

        # Initial progress update
        self.callbacks.debug("Processing uploaded file...")
        self.callbacks.progress(0, total_files, "Processing ZIP file")

        self.callbacks.log(f"⚙️ {title}{f' ({year})' if year else ''} • {author} | Obtained {total_files + skipped} asset(s) from uploaded {'MediUX' if source=="mediux" else 'TPDb'} ZIP file.")
        if skipped > 0:
            self.callbacks.log(f"⏩ {title}{f' ({year})' if year else ''} • {author} | Skipping {skipped} asset(s) based on filters. Processing {total_files} asset(s).")

        for index, artwork in enumerate(file_list, start=1):
            # Update progress
            self.callbacks.progress(index, total_files, f"Processing ZIP file • {index} of {total_files}")
            # Override title if provided
            if override_title:
                artwork['title'] = override_title

            media_type = artwork.get('media')

            # Call the appropriate processor method based on media type
            if media_type == "Collection":
                process_func = processor.process_collection_artwork
            elif media_type == "Movie":
                process_func = processor.process_movie_artwork
            elif media_type == "TV Show":
                process_func = processor.process_tv_artwork
            elif media_type == "unavailable":
                self.callbacks.log(f"⚠️ {artwork['title']} {f"({artwork['year']})" if artwork.get('year') else ''} : {artwork['author']} | Movie or TV Show not available on Plex")
                os.remove(artwork['path'])  # Remove the temporary file after processing
                try:
                    os.rmdir(os.path.dirname(artwork['path']))  # Remove the temporary directory if empty
                    self.callbacks.debug(f"Deleted temporary directory: {os.path.dirname(artwork['path'])}")
                except OSError as e:
                    self.callbacks.debug(f"Error deleting temporary directory: {os.path.dirname(artwork['path'])} - {str(e)}")
                    pass
                continue
            else:
                self.callbacks.log(f"❌ Unknown media type: {media_type}")
                continue

            # Build status message
            season_info = f" - Season {artwork['season']}" if artwork.get('season') else ""
            episode_info = f", Episode {artwork['episode']}" if artwork.get('episode') else ""
            status_msg = f'Processing {media_type.lower()} artwork for "{artwork["title"]}"{season_info}{episode_info}'

            # Debug logging
            self.callbacks.debug(status_msg)

            # Update status
            self.callbacks.status(
                status_msg,
                "info",
                True,  # spinner
                True   # sticky
            )

            # Process the artwork if media_type is known
            if media_type != "unavailable":
                try:
                    results = process_func(artwork)

                    for result in results:
                        # Track successful uploads (those starting with ✅ or ♻️)
                        if result.startswith('✅') or result.startswith('♻️'):
                            success_counter += 1

                        # Log the result
                        self.callbacks.log(result)

                except CollectionNotFound as e:
                    self.callbacks.log(f"⚠️ {str(e)}")

                except MovieNotFound as e:
                    self.callbacks.log(f"⚠️ {str(e)}")

                except ShowNotFound as e:
                    self.callbacks.log(f"⚠️ {str(e)}")

                except NotProcessedByExclusion as e:
                    self.callbacks.log(f"⏩ {str(e)}")

                except NotProcessedByFilter as e:
                    self.callbacks.log(f"⏩ {str(e)}")

                except Exception as e:
                    self.callbacks.log(f"❌ {str(e)}")
            try:
                os.remove(artwork['path'])  # Remove the temporary file after processing
                self.callbacks.debug(f"Deleted temporary file: {artwork['path']}")
            except OSError as e:
                self.callbacks.debug(f"Failed to delete temporary file: {artwork['path']} - {str(e)}")
                pass
            try:
                os.rmdir(os.path.dirname(artwork['path']))  # Remove the temporary directory if empty
                self.callbacks.debug(f"Deleted temporary directory: {os.path.dirname(artwork['path'])}")
            except OSError:
                pass
        # Final progress update
        self.callbacks.log(f"✔️ {title}{f' ({year})' if year else ''} • {author} | {total_files} file(s) processed • {success_counter} asset(s) updated.")
        self.callbacks.progress(total_files, total_files, f"Processing ZIP file • {total_files} of {total_files}")
