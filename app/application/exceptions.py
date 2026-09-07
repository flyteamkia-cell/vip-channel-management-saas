class ApplicationError(Exception):
    """Base application exception"""


class EntityNotFoundError(ApplicationError):
    pass


class ProviderUnavailableError(ApplicationError):
    pass
