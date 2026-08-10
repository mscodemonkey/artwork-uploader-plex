"""
Retry helper for the upload path (Plex uploads and Kometa asset downloads).

A transient failure - a timeout, a dropped connection, or a 5xx response - is worth trying again.
An authentication or not-found error is not: retrying it wastes the attempts budget on something
that will never succeed.
"""

import re
import time
import requests
import plexapi.exceptions


def is_transient_error(exc: Exception) -> bool:
    """True for a timeout, connection failure, or 5xx response. False for everything else,
       including a 401 or a 404."""
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return True

    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status is not None and 500 <= status < 600

    # plexapi doesn't raise requests.exceptions.HTTPError for a bad status code from the Plex
    # server - it raises BadRequest (or Unauthorized, a subclass of BadRequest, for a 401) with
    # the status code embedded in the message as "(NNN) ...".
    if isinstance(exc, plexapi.exceptions.BadRequest) and not isinstance(exc, plexapi.exceptions.Unauthorized):
        match = re.match(r"\((\d{3})\)", str(exc))
        return bool(match) and 500 <= int(match.group(1)) < 600

    return False


def call_with_retry(func, attempts: int, backoff: float):
    """
    Calls func(), retrying on a transient error until it succeeds or `attempts` attempts (the
    first call plus any retries) have been made. Waits `backoff * 2 ** n` seconds between
    attempts, doubling each time.

    Returns (result, attempts_made) on success. On failure, re-raises the last exception with an
    `attempts` attribute set to the number of attempts made, so the caller can report it.
    """
    attempts = max(attempts, 1)
    for attempt in range(1, attempts + 1):
        try:
            return func(), attempt
        except Exception as e:
            if attempt >= attempts or not is_transient_error(e):
                e.attempts = attempt
                raise
            time.sleep(backoff * (2 ** (attempt - 1)))
