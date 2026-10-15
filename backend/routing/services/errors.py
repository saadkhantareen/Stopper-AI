class BadInputError(Exception):
    """The user's input is invalid or a place could not be found (HTTP 400)."""


class UpstreamError(Exception):
    """An upstream API failed or returned no usable result (HTTP 502)."""
