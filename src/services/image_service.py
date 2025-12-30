"""
Service for image processing utilities.

Extracted from artwork_uploader.py to reduce file size and improve
maintainability.
"""

from typing import Literal

from PIL import Image


class ImageService:
    """Handles image processing operations."""

    @staticmethod
    def check_orientation(image_path: str) -> Literal["landscape", "portrait", "square"]:
        """
        Check the orientation of an image.

        Args:
            image_path: Path to the image file

        Returns:
            "landscape", "portrait", or "square"

        Raises:
            FileNotFoundError: If image file doesn't exist
            Exception: If image cannot be opened
        """
        with Image.open(image_path) as img:
            width, height = img.size

        if width > height:
            return "landscape"
        elif width < height:
            return "portrait"
        else:
            return "square"

    @staticmethod
    def get_dimensions(image_path: str) -> tuple[int, int]:
        """
        Get the dimensions of an image.

        Args:
            image_path: Path to the image file

        Returns:
            Tuple of (width, height)

        Raises:
            FileNotFoundError: If image file doesn't exist
            Exception: If image cannot be opened
        """
        with Image.open(image_path) as img:
            return img.size
