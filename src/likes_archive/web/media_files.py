"""StaticFiles subclass for the ``/media`` mount.

Tweet media is stored under its dedup key with the file extension stripped
(``images/tweets/HMDX…``, not ``…​.jpg``): the full-quality upgrade puts the
format in the query string (``?format=jpg&name=orig``) and the key is derived
from the URL *path*, so the extension is lost. Plain ``StaticFiles`` then guesses
the content type from the (absent) extension, serving ``application/octet-stream``
with no filename — so a right-click "Save image as…" yields an extensionless file.

``MediaFiles`` fixes both at serve time, without touching storage:

* sniff the real type from the file's magic bytes and correct ``Content-Type``, and
* send ``Content-Disposition: inline; filename="…​.jpg"`` so a manual save gets a
  proper name + extension while the image still renders inline in the page.
"""

from __future__ import annotations

import os

from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

# (magic-byte prefix, MIME type, extension) for the formats Twitter media uses.
_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
)

# Content types that mean "I couldn't tell" — the ones worth overriding.
_GENERIC = frozenset({"", "application/octet-stream"})


def sniff_media_type(head: bytes) -> tuple[str, str] | None:
    """Return ``(mime, extension)`` for a file's first bytes, or ``None``.

    Covers the container-based formats (WebP/MP4) whose signature is not a plain
    prefix in addition to the prefix-based image formats.
    """
    for magic, mime, ext in _SIGNATURES:
        if head.startswith(magic):
            return mime, ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if head[4:8] == b"ftyp":
        return "video/mp4", ".mp4"
    return None


class MediaFiles(StaticFiles):
    """Serve media files with a sniffed content type and an inline filename."""

    def file_response(
        self,
        full_path: os.PathLike[str] | str,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        # Skip 304 Not Modified (no body) — only real file bodies need the headers.
        if isinstance(response, FileResponse):
            _apply_headers(response, os.fspath(full_path))
        return response


def _apply_headers(response: FileResponse, full_path: str) -> None:
    name = os.path.basename(full_path)
    _, ext = os.path.splitext(name)
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()

    # Only read bytes when the name/type can't already answer it.
    if not ext or content_type in _GENERIC:
        with open(full_path, "rb") as fh:
            sniffed = sniff_media_type(fh.read(16))
        if sniffed is not None:
            mime, sniffed_ext = sniffed
            response.headers["content-type"] = mime
            if not ext:
                name += sniffed_ext

    response.headers["content-disposition"] = f'inline; filename="{name}"'
