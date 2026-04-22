"""HTTP helpers that restrict requests to http(s) URLs."""

from __future__ import annotations

from urllib.parse import urlparse
from urllib.request import Request, urlopen

_ALLOWED_SCHEMES = ("http", "https")


def safe_urlopen(req_or_url, *args, **kwargs):
    """urlopen, but reject non-http(s) schemes before dispatching.

    Prevents file:// and custom-scheme reads when the URL is derived from
    user-configurable settings.
    """
    url = req_or_url.full_url if isinstance(req_or_url, Request) else req_or_url
    scheme = urlparse(url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Refusing to open URL with scheme {scheme!r}")
    return urlopen(req_or_url, *args, **kwargs)  # nosec B310
