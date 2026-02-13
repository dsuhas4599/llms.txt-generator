from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse


def normalize_url(url: str, base: str | None = None) -> str:
    if base:
        url = urljoin(base, url)
    parsed = urlparse(url)
    netloc = parsed.netloc
    if netloc and ":" in netloc and netloc.endswith((":80", ":443")):
        host, port = netloc.rsplit(":", 1)
        if (parsed.scheme == "https" and port == "443") or (
            parsed.scheme == "http" and port == "80"
        ):
            netloc = host
    normalized = urlunparse(
        (parsed.scheme or "https", netloc, parsed.path or "/", parsed.params, parsed.query, "")
    )
    return normalized.rstrip("/") or normalized


def get_origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme or 'https'}://{parsed.netloc}"


def is_same_origin(url: str, base_origin: str) -> bool:
    """Return True if url belongs to the same origin as base_origin."""
    return get_origin(url) == base_origin


def get_robots_url(base_url: str) -> str:
    origin = get_origin(base_url)
    return urljoin(origin + "/", "robots.txt")


def get_sitemap_url(base_url: str) -> str:
    origin = get_origin(base_url)
    return urljoin(origin + "/", "sitemap.xml")
