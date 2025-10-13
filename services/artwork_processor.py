"""
Service for coordinating artwork scraping and uploading.

This service handles the business logic of scraping artwork and processing
it for upload to Plex, separating it from UI/notification concerns.
"""

from typing import Optional, Callable, Any
from dataclasses import dataclass

from scrapers.scraper import Scraper
from processors.upload_processor import UploadProcessor
from plex.plex_connector import PlexConnector
from models.options import Options
from core.exceptions import (
    PlexConnectorException,
    ScraperException,
    CollectionNotFound,
    MovieNotFound,
    ShowNotFound,
    NotProcessedByFilter,
    NotProcessedByExclusion
)


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

        return title

    def _process_single_artwork(
        self,
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
                    True   # sticky
                )

            # Process the artwork
            result = process_func(artwork)

            # Log the result
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(result)

        except CollectionNotFound as e:
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(f"∙ {str(e)}")

        except MovieNotFound as e:
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(f"∙ {str(e)}")

        except ShowNotFound as e:
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(f"∙ {str(e)}")

        except NotProcessedByExclusion as e:
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(f"- {str(e)}")

        except NotProcessedByFilter as e:
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(f"- {str(e)}")

        except Exception as e:
            if callbacks and callbacks.on_log_update:
                callbacks.on_log_update(f"x {str(e)}")
            if callbacks and callbacks.on_status_update:
                callbacks.on_status_update(
                    f"Error: {str(e)}",
                    "danger",
                    False,  # no spinner
                    False   # not sticky
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

        # Initial progress update
        if callbacks and callbacks.on_debug:
            callbacks.on_debug("Processing uploaded file and uploading to Plex...", "process_uploaded_artwork")
        if callbacks and callbacks.on_progress_update:
            callbacks.on_progress_update(0, total_files)

        for index, artwork in enumerate(file_list, start=1):
            # Update progress
            if callbacks and callbacks.on_progress_update:
                callbacks.on_progress_update(index, total_files)
            # Override title if provided
            if override_title:
                artwork['title'] = override_title

            # Determine the processor method based on media type
            media_type = artwork.get('media', 'Unknown')

            if media_type == "Collection":
                process_func = processor.process_collection_artwork
            elif media_type == "Movie":
                process_func = processor.process_movie_artwork
            elif media_type == "TV Show":
                process_func = processor.process_tv_artwork
            else:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"x Unknown media type: {media_type}")
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
                    True   # sticky
                )

            # Process the artwork
            try:
                result = process_func(artwork)
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(result)

            except CollectionNotFound as e:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"∙ {str(e)}")

            except MovieNotFound as e:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"∙ {str(e)}")

            except ShowNotFound as e:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"∙ {str(e)}")

            except NotProcessedByExclusion as e:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"- {str(e)}")

            except NotProcessedByFilter as e:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"- {str(e)}")

            except Exception as e:
                if callbacks and callbacks.on_log_update:
                    callbacks.on_log_update(f"x Unexpected during process_uploaded_artwork: {str(e)}")
                if callbacks and callbacks.on_status_update:
                    callbacks.on_status_update(
                        f"Error: {str(e)}",
                        "danger",
                        False,  # no spinner
                        False   # not sticky
                    )

        # Final progress update
        if callbacks and callbacks.on_progress_update:
            callbacks.on_progress_update(total_files, total_files)
