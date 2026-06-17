from __future__ import annotations


class TokenExpiredError(Exception):
    """Raised when the X session credentials return HTTP 401 or 403.

    The scraper runner reads the status code so it can log it precisely and
    the web app reads the most recent scrape_runs row to surface a banner.
    """

    def __init__(self, *, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"X session token expired (HTTP {status_code})")


class MediaNotFound(Exception):
    """Raised by FilesystemMediaStore.get() when a key is absent on disk.

    Callers that need to distinguish a missing file from other I/O errors
    catch this specifically; everything else propagates as OSError.
    """

    def __init__(self, *, key: str) -> None:
        self.key = key
        super().__init__(f"Media key not found: {key}")
