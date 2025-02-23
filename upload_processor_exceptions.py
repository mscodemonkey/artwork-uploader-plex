# -*- coding: utf-8 -*-


class UploadProcessorException(Exception):
    """ Base class for all PlexConnector exceptions. """
    def __init__(self, message):
        super().__init__(message)

class CollectionNotFound(UploadProcessorException):
    """ A collection was not found for the artwork provided """

class ShowNotFound(UploadProcessorException):
    """ A tv show was not found for the artwork provided """

class MovieNotFound(UploadProcessorException):
    """ A movie was not found for the artwork provided """

class NotProcessedByFilter(UploadProcessorException):
    """ An item was not uploaded due to a filter being applied """

class NotProcessedByExclusion(UploadProcessorException):
    """ An item was not uploaded due to an exception being applied """