"""
URL item with associated scraping options.
"""

from dataclasses import dataclass

from models.options import Options


@dataclass
class URLItem:
    """
    Represents a URL paired with its scraping options.

    Used for parsing bulk import files where each line contains a URL
    followed by optional command-line style arguments.

    Attributes:
        url: The URL to scrape (ThePosterDB or MediUX)
        options: Associated Options object with filters, force flags, etc.
    """

    url: str
    options: Options
