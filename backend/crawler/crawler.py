import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .robots import get_robots_policy, is_path_allowed
from .sitemap import fetch_sitemap_urls
from .url_utils import get_origin, is_same_origin, normalize_url

USER_AGENT = "llms-txt-generator/1.0 (+https://github.com/llms-txt-generator)"


@dataclass
class PageInfo:
    url: str
    title: str
    description: str = ""


@dataclass
class CrawlOptions:
    """Options for crawl_site."""
    max_pages: int = 10
    timeout: int = 10
    crawl_delay: float = 0.5
    respect_robots: bool = True
    use_sitemap: bool = True
    sitemap_max_urls: int = 500


def _extract_metadata(html: str, url: str) -> PageInfo:
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    desc = ""

    tag = soup.find("title")
    if tag and tag.string:
        title = tag.string.strip() or ""
    if not title:
        title = url  # fallback

    # meta name="description"
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        desc = meta["content"].strip()
    if not desc:
        meta = soup.find("meta", attrs={"property": "og:description"})
        if meta and meta.get("content"):
            desc = meta["content"].strip()

    return PageInfo(url=url, title=title, description=desc)


def _extract_links(html: str, base_url: str, same_origin: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        u = normalize_url(href, base_url)
        if is_same_origin(u, same_origin) and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def crawl_site(base_url: str, options: CrawlOptions | None = None) -> list[PageInfo]:
    opts = options or CrawlOptions()
    base_url = normalize_url(base_url)
    origin = get_origin(base_url)
    logger.info("Crawl starting: url=%s max_pages=%d", base_url, opts.max_pages)

    disallowed_patterns: list[str] = []
    delay = opts.crawl_delay
    if opts.respect_robots:
        disallowed_patterns, robots_delay = get_robots_policy(origin, timeout=opts.timeout)
        if robots_delay > 0:
            delay = robots_delay

    def path_allowed(url: str) -> bool:
        path = urlparse(url).path or "/"
        return is_path_allowed(path, disallowed_patterns)

    to_visit: list[str] = []
    if opts.use_sitemap:
        sitemap_urls = fetch_sitemap_urls(
            origin, timeout=opts.timeout, max_urls=opts.sitemap_max_urls
        )
        for u in sitemap_urls:
            if path_allowed(u):
                to_visit.append(u)
    logger.info("Sitemap URLs: %s", sitemap_urls)
    if not to_visit:
        to_visit = [base_url]
    logger.info("Crawl seed: %d URLs to visit (sitemap=%s)", len(to_visit), opts.use_sitemap)

    visited: set[str] = set[str]()
    results: list[PageInfo] = []

    while to_visit and len(results) < opts.max_pages:
        url = to_visit.pop(0)
        if url in visited:
            continue
        if not path_allowed(url):
            continue
        visited.add(url)

        try:
            r = requests.get(
                url,
                timeout=opts.timeout,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True,
            )
            if r.status_code != 200:
                continue
            final_url = normalize_url(r.url)
            if final_url != url:
                visited.add(final_url)
            html = r.text
        except Exception:
            continue

        info = _extract_metadata(html, final_url)
        results.append(info)
        if len(results) % 10 == 0 or len(results) == 1:
            logger.info("Crawled %d pages so far (current: %s)", len(results), final_url[:80])

        for link in _extract_links(html, final_url, origin):
            logger.info("Link: %s", link)
            if link not in visited and link not in to_visit and path_allowed(link):
                logger.info("Adding link to visit: %s", link)
                to_visit.append(link)

        if delay > 0:
            time.sleep(delay)

    logger.info("Crawl finished: %d pages from %s", len(results), base_url)
    return results
