"""MediaStore ABC and FilesystemMediaStore implementation.

This module is intentionally self-contained — it imports nothing from
likes_archive.db or likes_archive.web — so ingestion/, migrate.py, and
tests may import it freely without pulling in FastAPI or SQLAlchemy.

Future swap-point
-----------------
A future ``S3MediaStore`` would implement the same four abstract methods
using boto3 (or aiobotocore):

- ``put(key, data)``   → ``s3.put_object(Bucket=bucket, Key=key, Body=data)``
- ``get(key)``         → ``s3.get_object(...)[\"Body\"].read()``
- ``exists(key)``      → ``s3.head_object(...)`` wrapped in try/except
- ``url_for(key)``     → pre-signed URL or CDN prefix + key

Backend selection would be a ``MEDIA_BACKEND`` env var resolved once in
``create_app()`` / the scraper runner, keeping every caller unchanged.
Not built now (Milestone 2 is filesystem-only).
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from likes_archive.exceptions import MediaNotFound


class MediaStore(ABC):
    """Abstract interface for a binary media object store.

    All keys are relative POSIX path strings, e.g.
    ``"images/tweets/AbCdEf.jpg"`` or ``"images/avatars/123456789.jpg"``.
    Callers never construct physical paths or serve URLs directly.
    """

    @abstractmethod
    def put(self, key: str, data: bytes) -> None:
        """Write *data* at *key*, creating it or overwriting existing content."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Return the raw bytes stored at *key*.

        Raises:
            MediaNotFound: if *key* does not exist in the store.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return ``True`` if *key* is present, ``False`` otherwise."""

    @abstractmethod
    def url_for(self, key: str) -> str:
        """Return the URL at which *key* is publicly reachable."""


class FilesystemMediaStore(MediaStore):
    """MediaStore backed by a local (or NFS-mounted) directory tree.

    Parameters
    ----------
    media_root:
        Absolute path to the root directory (the ``MEDIA_ROOT`` env var, a
        pydantic-settings ``Path``). On the LXC host this is the NFS
        bind-mount, e.g. ``/mnt/media/likes``. The subtree mirrors the legacy
        ``tweet_likes_html/`` layout: ``images/avatars/``, ``images/tweets/``,
        ``videos/tweets/``.
    base_url:
        URL prefix returned by ``url_for()`` (the ``MEDIA_BASE_URL`` env var).
        Defaults to ``"/media"`` (the FastAPI StaticFiles mount). Set to a full
        public URL when the reverse proxy serves files directly from
        *media_root* — no code changes needed to switch serving strategies.
    """

    def __init__(self, media_root: Path, base_url: str) -> None:
        self._media_root = media_root
        self._base_url = base_url.rstrip("/")

    def put(self, key: str, data: bytes) -> None:
        """Write *data* at *key* atomically.

        The temp file is created in ``dest.parent`` (same directory, same NFS
        export) so ``os.replace()`` is atomic and a half-written file is never
        visible under its final key. Any exception removes the temp file.
        """
        dest = self._media_root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".dl_", dir=dest.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def get(self, key: str) -> bytes:
        path = self._media_root / key
        if not path.exists():
            raise MediaNotFound(key=key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return (self._media_root / key).exists()

    def url_for(self, key: str) -> str:
        return f"{self._base_url}/{key}"
