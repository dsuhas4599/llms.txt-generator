import re
from urllib.parse import urlparse

import requests

from .url_utils import get_origin, get_robots_url

USER_AGENT = "llms-txt-generator/1.0 (+https://github.com/llms-txt-generator)"
DEFAULT_CRAWL_DELAY = 0.5


def fetch_robots_txt(site_origin: str, timeout: int = 10) -> str:
    url = get_robots_url(site_origin)
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""


def parse_robots(robots_txt: str, user_agent: str = "*") -> tuple[list[str], float]:
    disallowed: list[str] = []
    crawl_delay = 0.0
    current_agents: list[str] | None = None
    block_disallowed: list[str] = []
    block_delay: float | None = None
    found_star_block = False

    def flush_block():
        nonlocal disallowed, crawl_delay, found_star_block, block_delay
        if current_agents and "*" in current_agents and not found_star_block:
            disallowed = list(block_disallowed)
            if block_delay is not None:
                crawl_delay = block_delay
            found_star_block = True
        block_disallowed.clear()
        block_delay = None

    for line in robots_txt.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.lower().startswith("user-agent:"):
            flush_block()
            agent = line.split(":", 1)[1].strip().lower()
            current_agents = [agent]
        elif current_agents is not None:
            low = line.lower()
            if low.startswith("disallow:"):
                path = line.split(":", 1)[1].strip()
                if path:
                    pattern = re.escape(path).replace(r"\*", ".*")
                    block_disallowed.append(pattern)
            elif low.startswith("crawl-delay:"):
                try:
                    value = line.split(":", 1)[1].strip().split()[0]
                    block_delay = float(value)
                except (ValueError, IndexError):
                    pass

    flush_block()
    return disallowed, crawl_delay


def is_path_allowed(path: str, disallowed_patterns: list[str]) -> bool:
    """Return False if path is disallowed by any of the patterns (regex match)."""
    if not path:
        path = "/"
    if not path.startswith("/"):
        path = "/" + path
    for pattern in disallowed_patterns:
        if re.match(pattern, path):
            return False
    return True


def get_robots_policy(site_origin: str, timeout: int = 10) -> tuple[list[str], float]:
    """
    Fetch and parse robots.txt for site_origin.
    Returns (disallowed_path_patterns, crawl_delay_seconds).
    Uses DEFAULT_CRAWL_DELAY if robots.txt has no Crawl-delay.
    """
    text = fetch_robots_txt(site_origin, timeout=timeout)
    disallowed, crawl_delay = parse_robots(text)
    if crawl_delay <= 0:
        crawl_delay = DEFAULT_CRAWL_DELAY
    return disallowed, crawl_delay
