class AlreadyRegistered(LookupError):
    """Raised when a model or page key is registered twice."""


class NotRegistered(LookupError):
    """Raised when a URL references a resource not present in the site."""


class InvalidResourceConfiguration(ValueError):
    """A developer-facing resource configuration error."""
