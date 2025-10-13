"""
Service layer for business logic.

This package contains service classes that encapsulate business logic
to reduce the size of the monolithic artwork_uploader.py file.
"""

from .bulk_file_service import BulkFileService
from .image_service import ImageService
from .artwork_processor import ArtworkProcessor, ProcessingCallbacks
from .scheduler_service import SchedulerService
from .update_service import UpdateService
from .utility_service import UtilityService
from .authentication_service import AuthenticationService

__all__ = [
    'BulkFileService',
    'ImageService',
    'ArtworkProcessor',
    'ProcessingCallbacks',
    'SchedulerService',
    'UpdateService',
    'UtilityService',
    'AuthenticationService'
]
