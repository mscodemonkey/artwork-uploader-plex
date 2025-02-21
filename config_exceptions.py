class ConfigException(Exception):
    """ Base class for all PlexConnector exceptions. """
    def __init__(self, message):
        super().__init__(message)

class ConfigCreationError(ConfigException):
    """ A collection was not found for the artwork provided """

class ConfigLoadingError(ConfigException):
    """ A collection was not found for the artwork provided """

class ConfigSavingError(ConfigException):
    """ A collection was not found for the artwork provided """