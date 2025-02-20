# -*- coding: utf-8 -*-


class PlexConnectorException(Exception):
    """ Base class for all PlexConnector exceptions. """
    def __init__(self, message, gui_message = None):
        super().__init__(message)
        self.gui_message = gui_message if gui_message is not None else message

class LibraryNotFound(PlexConnectorException):
    """ An invalid request, generally a user error. """


