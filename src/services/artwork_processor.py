"""
Service for coordinating artwork scraping and uploading.

This service handles the business logic of scraping artwork and processing
it for upload to Plex, separating it from UI/notification concerns.
"""

import os
from dataclasses import dataclass
from typing import Optional, Callable

from core.exceptions import (
    PlexConnectorException,
    ScraperException,
    CollectionNotFound,
    MovieNotFound,
    ShowNotFound,
    NotProcessedByFilter,
    NotProcessedByExclusion
)
from models.options import Options
from plex.plex_connector import PlexConnector
from processors.upload_processor import UploadProcessor
from scrapers.scraper import Scraper


@dataclass
class ProcessingCallbacks:
    """
    Callbacks for UI updates during artwork processing.

    All callbacks are optional and called with appropriate arguments
    when processing events occur.
    """
    on_status_update: Optional[Callable[[str, str, bool, bool], None]] = None  # (message, color, spinner, sticky)
    on_log_update: Optional[Callable[[str], None]] = None  # (message)
    on_progress_update: Optional[Callable[[int, int], None]] = None  # (current, total) - for progress bars
    on_debug: Optional[Callable[[str, str], None]] = None  # (message, context) - for debug messages
    success_counter: Optional[
        list] = None  # Mutable list to track successful uploads (contains count as single element)


class ArtworkProcessor:
    """Coordinates scraping and uploading of artwork."""

    def __init__(self, plex: PlexConnector) -> None:
        self.plex = plex

    def scrape_and_process(
            self,
            url: str,
            options: Options,
            callbacks: Optional[ProcessingCallbacks] = None
    ) -> Optional[str]:
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
        self.plex.connect()

        # Scrape the artwork
        scraper = Scraper(url)
        scraper.set_options(options)
        scraper.scrape()
        title = scraper.title

        # Process the scraped artwork
        processor = UploadProcessor(self.plex)
        processor.set_options(options)

        if callbacks and callbacks.on_log_update:
            # callbacks.on_log_update(f"🔍 Scraping artwork{f" for '{title}'" if title else ""} by '{scraper.author}'")
            callbacks.on_log_update(
                f"🔍 {title} : {scraper.author} | Scraping from {f"ThePosterDB" if scraper.source == "theposterdb" else "Mediux"}")
            if scraper.exclusions > 0:
                callbacks.on_log_update(
                    f"⏩ {title} : {scraper.author} | Skipped {scraper.exclusions} asset(s) based on exclusions.")

        # Process collections
        for artwork in scraper.collection_artwork:
            self._process_single_artwork(
                artwork,
                processor.process_collection_artwork,
                callbacks
            )

        # Process movies
        for artwork in scraper.movie_artwork:
            self._process_single_artwork(
                artwork,
                processor.process_movie_artwork,
                callbacks
            )

        # Process TV shows
        for artwork in scraper.tv_artwork:
            self._process_single_artwork(
                artwork,
                processor.process_tv_artwork,
                callbacks
            )
        callbacks.on_log_update("✔️ Scraping completed")
        return title

    @staticmethod
    def _process_single_artwork(
            artwork: dict,
            process_func: Callable[[dict], str],
            callbacks: Optional[ProcessingCallbacks]
    ) -> None:
        """
        Process a single piece of artwork with error handling.

        Args:
            artwork: Artwork dictionary
            process_func: Function to process the artwork (from UploadProcessor)
            callbacks: Optional callbacks for UI updates
        """
        try:
            # Update status if callback provided
            if callbacks and callbacks.on_status_update:
                callbacks.on_status_update(
                    f'Processing artwork for {artwork["title"]}',
                    "info",
                    True,  # spinner
                    True  # sticky
                )

            # Process the artwork
            results = process_func(artwork)

            for result in results:
                # Track successful uploads (those starting with ✅ or ♻️)
                if callbacks and callbacks.success_counter is not None and (
                        result.startswith('✅') or result.startswith('♻️')):
                    callbacks.success_counter[0] += 1

                # Log the result
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(result)

        except CollectionNotFound as e:
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(f"⚠️ {str(e)}")

        except MovieNotFound as e:
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(f"⚠️ {str(e)}")

        except ShowNotFound as e:
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(f"⚠️ {str(e)}")

        except NotProcessedByExclusion as e:
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(f"⏩ {str(e)}")

        except NotProcessedByFilter as e:
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(f"⏩ {str(e)}")

        except Exception as e:
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(f"❌ {str(e)}")
            if callbacks and callbacks.on_status_update:
                callbacks.on_status_update(
                    f"Error: {str(e)}",
                    "danger",
                    False,  # no spinner
                    False  # not sticky
                )

    def process_uploaded_files(
            self,
            file_list: list[dict],
            options: Options,
            callbacks: Optional[ProcessingCallbacks] = None,
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
        file_source = file_list[0].get('source', 'unknown')
        source = "Mediux" if file_source == "mediux" else "ThePosterDB" if file_source == "theposterdb" else "Unknown"
        author = file_list[0].get('author', 'unknown')
        title = override_title if override_title else file_list[0].get('title', 'unknown')
        year = file_list[0].get('year', 'unknown')
        success_counter = 0  # Mutable counter to track successful uploads

        # Initial progress update
        if callbacks and callbacks.on_debug:
            callbacks.on_debug("Processing uploaded file...", "process_uploaded_artwork")
        if callbacks and callbacks.on_progress_update:
            callbacks.on_progress_update(0, total_files)

        if callbacks and callbacks.on_log_update:
            # callbacks.on_log_update(f"⚙️ Processing {source} ZIP file by {author} for {title} ({year}).")
            callbacks.on_log_update(
                f"⚙️ {title}{f" ({year})" if year else ''} : {author} | Processing uploaded {source} ZIP file.")

        for index, artwork in enumerate(file_list, start=1):
            # Update progress
            if callbacks and callbacks.on_progress_update:
                callbacks.on_progress_update(index, total_files)
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
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(
                        f"⚠️ {artwork['title']} {f"({artwork['year']})" if artwork.get('year') else ''} : {artwork['author']} | Not available in Plex.")
                    os.remove(artwork['path'])  # Remove the temporary file after processing
                    try:
                        os.rmdir(os.path.dirname(artwork['path']))  # Remove the temporary directory if empty
                        callbacks.on_debug(f"Deleted temporary directory: {os.path.dirname(artwork['path'])}",
                                           "process_uploaded_artwork")
                    except OSError:
                        pass
                    continue
            else:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"❌ Unknown media type: {media_type}")
                continue

            # Build status message
            season_info = f" - Season {artwork['season']}" if artwork.get('season') else ""
            episode_info = f", Episode {artwork['episode']}" if artwork.get('episode') else ""
            status_msg = f'Processing artwork for {media_type.lower()} "{artwork["title"]}"{season_info}{episode_info}'

            # Debug logging
            if callbacks and callbacks.on_debug:
                callbacks.on_debug(status_msg, "process_uploaded_artwork")

            # Update status
            if callbacks and callbacks.on_status_update:
                callbacks.on_status_update(
                    status_msg,
                    "info",
                    True,  # spinner
                    True  # sticky
                )

            # Process the artwork
            try:
                results = process_func(artwork)

                for result in results:
                    # Track successful uploads (those starting with ✅ or ♻️)
                    if result.startswith('✅') or result.startswith('♻️'):
                        success_counter += 1

                    # Log the result
                    if callbacks and callbacks.on_log_update:
                        callbacks.on_log_update(result)

            except CollectionNotFound as e:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"⚠️ {str(e)}")

            except MovieNotFound as e:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"⚠️ {str(e)}")

            except ShowNotFound as e:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"⚠️ {str(e)}")

            except NotProcessedByExclusion as e:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"⏩ {str(e)}")

            except NotProcessedByFilter as e:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"⏩ {str(e)}")

            except Exception as e:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"❌ Unexpected during process_uploaded_artwork: {str(e)}")
                if callbacks and callbacks.on_status_update:
                    callbacks.on_status_update(
                        f"Error: {str(e)}",
                        "danger",
                        False,  # no spinner
                        False  # not sticky
                    )
            os.remove(artwork['path'])  # Remove the temporary file after processing
            try:
                os.rmdir(os.path.dirname(artwork['path']))  # Remove the temporary directory if empty
                callbacks.on_debug(f"Deleted temporary directory: {os.path.dirname(artwork['path'])}",
                                   "process_uploaded_artwork")
            except OSError:
                pass
        # Final progress update
        if callbacks and callbacks.on_log_update:
            callbacks.on_log_update(f"✔️ Finished processing uploaded ZIP file. {success_counter} assets updated.")
        if callbacks and callbacks.on_progress_update:
            callbacks.on_progress_update(total_files, total_files)
