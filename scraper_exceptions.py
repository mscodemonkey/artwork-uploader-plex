# -*- coding: utf-8 -*-


class ScraperException(Exception):
    """ Base class for all PlexConnector exceptions. """
    def __init__(self, message):
        super().__init__(message)
