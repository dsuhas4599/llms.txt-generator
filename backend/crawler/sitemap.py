from xml.etree import ElementTree as ET

import requests

from .url_utils import get_origin, get_sitemap_url, is_same_origin, normalize_url

USER_AGENT = "llms-txt-generator/1.0 (+https://github.com/llms-txt-generator)"

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def fetch_sitemap_urls(site_origin: str, timeout: int = 10, max_urls: int = 500) -> list[str]:
    url = get_sitemap_url(site_origin)
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        if r.status_code != 200:
            return []
    except Exception:
        return []

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return []

    # Check for sitemap index: <sitemap><loc>...</loc></sitemap>
    sitemap_locs = root.findall(".//sm:sitemap/sm:loc", SITEMAP_NS)
    if not sitemap_locs:
        sitemap_locs = root.findall(".//sitemap/loc")  # no namespace

    if sitemap_locs:
        # Sitemap index: we only take the first sitemap to keep it simple and fast
        first_loc = sitemap_locs[0]
        if first_loc is not None and first_loc.text:
            child_url = first_loc.text.strip()
            return _urls_from_sitemap_xml(child_url, site_origin, timeout, max_urls)

    # Plain sitemap: <url><loc>...</loc></url>
    return _urls_from_sitemap_xml(url, site_origin, timeout, max_urls, root=root)


def _urls_from_sitemap_xml(
    source_url: str,
    site_origin: str,
    timeout: int,
    max_urls: int,
    root=None,
) -> list[str]:
    if root is None:
        try:
            r = requests.get(
                source_url,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True,
            )
            if r.status_code != 200:
                return []
            root = ET.fromstring(r.content)
        except Exception:
            return []

    url_locs = root.findall(".//sm:url/sm:loc", SITEMAP_NS)
    if not url_locs:
        url_locs = root.findall(".//url/loc")

    result = []
    for loc in url_locs:
        if loc is not None and loc.text:
            u = normalize_url(loc.text.strip())
            if is_same_origin(u, site_origin) and u not in result:
                result.append(u)
                if len(result) >= max_urls:
                    break
    return result
