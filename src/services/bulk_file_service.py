"""
Service for bulk import file I/O operations.

Extracted from artwork_uploader.py to reduce file size and improve
maintainability.
"""

import os
from pathlib import Path
from typing import Optional


class BulkFileService:
    """Handles bulk import file I/O operations."""

    def __init__(self, base_dir: str, bulk_imports_dir: Optional[str] = None) -> None:
        """
        Initialize the bulk file service.

        Args:
            base_dir: Base directory (usually from get_exe_dir())
            bulk_imports_dir: Bulk imports directory path. If absolute, ignores base_dir.
                             If None, uses BULK_IMPORTS_DIR env var or DEFAULT_BULK_IMPORTS_DIR.
        """
        from core.constants import DEFAULT_BULK_IMPORTS_DIR

        # Priority: explicit arg > env var > default constant
        if bulk_imports_dir is None:
            bulk_imports_dir = os.getenv("BULK_IMPORTS_DIR", DEFAULT_BULK_IMPORTS_DIR)

        # If absolute path, don't join with base_dir
        if os.path.isabs(bulk_imports_dir):
            self.base_dir = ""
            self.bulk_imports_path = bulk_imports_dir
        else:
            self.base_dir = base_dir
            self.bulk_imports_path = bulk_imports_dir

    def get_bulk_file_path(self, filename: Optional[str] = None) -> str:
        """
        Get the full path to a bulk import file.

        Args:
            filename: Name of the file (defaults to bulk_import.txt)

        Returns:
            Full path to the bulk import file
        """
        from core.constants import DEFAULT_BULK_IMPORT_FILE

        bulk_filename = filename if filename else DEFAULT_BULK_IMPORT_FILE

        if self.base_dir:
            return os.path.join(self.base_dir, self.bulk_imports_path, bulk_filename)
        return os.path.join(self.bulk_imports_path, bulk_filename)

    def get_bulk_imports_directory(self) -> Path:
        """
        Get the full path to the bulk_imports directory.

        Returns:
            Path object representing the bulk_imports directory
        """
        if self.base_dir:
            return Path(self.base_dir) / self.bulk_imports_path
        return Path(self.bulk_imports_path)

    def file_exists(self, filename: Optional[str] = None) -> bool:
        """
        Check if a bulk import file exists.

        Args:
            filename: Name of the file to check

        Returns:
            True if file exists, False otherwise
        """
        file_path = self.get_bulk_file_path(filename)
        return os.path.exists(file_path)

    def read_file(self, filename: Optional[str] = None) -> str:
        """
        Read contents of a bulk import file.

        Args:
            filename: Name of the file to read

        Returns:
            File contents as string

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        file_path = self.get_bulk_file_path(filename)

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")

        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()

    def write_file(self, contents: str, filename: Optional[str] = None) -> None:
        """
        Write contents to a bulk import file.

        Args:
            contents: Content to write
            filename: Name of the file to write

        Raises:
            IOError: If write fails
        """
        file_path = self.get_bulk_file_path(filename)

        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as file:
            file.write(contents)

    def rename_file(self, old_name: str, new_name: str) -> None:
        """
        Rename a bulk import file.

        Args:
            old_name: Current filename
            new_name: New filename

        Raises:
            FileNotFoundError: If old file doesn't exist
            FileExistsError: If new file already exists
        """
        old_path = self.get_bulk_file_path(old_name)
        new_path = self.get_bulk_file_path(new_name)

        if not os.path.exists(old_path):
            raise FileNotFoundError(f"File does not exist: {old_path}")

        if os.path.exists(new_path):
            raise FileExistsError(f"File already exists: {new_path}")

        os.rename(old_path, new_path)

    def delete_file(self, filename: str) -> None:
        """
        Delete a bulk import file.

        Args:
            filename: Name of the file to delete

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        file_path = self.get_bulk_file_path(filename)

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")

        os.remove(file_path)

    def ensure_default_file_exists(self, filename: Optional[str] = None) -> None:
        """
        Ensure a default bulk import file exists, create if it doesn't.

        Args:
            filename: Name of the file to ensure exists
        """
        file_path = self.get_bulk_file_path(filename)

        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Create default file if it doesn't exist
        if not os.path.isfile(file_path):
            default_contents = "## This is a blank bulk import file\n// You can use comments with # or // like this"
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(default_contents)
