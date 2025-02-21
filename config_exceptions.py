
class ConfigException(Exception):
    """ Base class for all config exceptions. """
    def __init__(self, message):
        super().__init__(message)

class ConfigCreationError(ConfigException):
    """ The config file could not be created """

class ConfigLoadError(ConfigException):
    """ The config file had a problem when loading """

class ConfigSaveError(ConfigException):
    """ The config file could not be saved """