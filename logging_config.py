"""
Logging configuration for Artwork Uploader.

Provides a centralized logging setup with file rotation and console output.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def setup_logging(debug: bool = False, log_file: Optional[str] = None) -> logging.Logger:
    """
    Configure application logging with file and console handlers.

    Args:
        debug: If True, set logging level to DEBUG, otherwise INFO
        log_file: Path to log file. If None, uses default 'logs/artwork_uploader.log'

    Returns:
        Configured logger instance for the application

    Example:
        >>> logger = setup_logging(debug=True)
        >>> logger.info("Application started")
        >>> logger.debug("Debug information")
    """
    # Create main application logger
    logger = logging.getLogger('artwork_uploader')
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create logs directory if it doesn't exist
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)

    # Determine log file path
    if log_file is None:
        log_file = log_dir / 'artwork_uploader.log'
    else:
        log_file = Path(log_file)

    # File handler with rotation (10MB per file, keep 5 backups)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO if not debug else logging.DEBUG)
    console_formatter = logging.Formatter(
        '%(levelname)s: %(message)s'
    )
    console_handler.setFormatter(console_formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.

    Args:
        name: Name of the module (usually __name__)

    Returns:
        Logger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Module loaded")
    """
    return logging.getLogger(f'artwork_uploader.{name}')


# Convenience function for quick logging without setup
def log_debug(message: str, module: str = "app") -> None:
    """Quick debug logging without needing a logger instance."""
    logging.getLogger(f'artwork_uploader.{module}').debug(message)


def log_info(message: str, module: str = "app") -> None:
    """Quick info logging without needing a logger instance."""
    logging.getLogger(f'artwork_uploader.{module}').info(message)


def log_warning(message: str, module: str = "app") -> None:
    """Quick warning logging without needing a logger instance."""
    logging.getLogger(f'artwork_uploader.{module}').warning(message)


def log_error(message: str, module: str = "app", exc_info: bool = False) -> None:
    """Quick error logging without needing a logger instance."""
    logging.getLogger(f'artwork_uploader.{module}').error(message, exc_info=exc_info)
