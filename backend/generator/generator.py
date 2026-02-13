"""Generate llms.txt markdown from PageInfo. Spec: https://llmstxt.org/"""
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)
from dataclasses import dataclass
from urllib.parse import urlparse

try:
    from crawler import PageInfo
except ImportError:
    PageInfo = None  # type: ignore


@dataclass
class GeneratorOptions:
    site_name: str | None = None
    summary: str | None = None
    base_url: str | None = None
    default_section: str = "Main"
    auto_sections: bool = True
    section_rules: list[tuple[str, str]] | None = None
    segment_rules: list[tuple[str, str]] | None = None
    optional_paths: list[str] | None = None


_LOCALE_LIKE = frozenset({
    "en", "de", "fr", "es", "it", "pt", "ja", "zh", "ko", "nl", "pl", "ru", "tr",
    "en-us", "en-gb", "es-mx", "pt-br", "zh-cn", "zh-tw", "en-au", "en-in",
})

_OPTIONAL_SEGMENTS = frozenset({"legal", "privacy", "terms", "cookies", "cookie", "optional"})


def _escape_md(s: str) -> str:
    if not s:
        return s
    return s.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _normalize_for_compare(url: str) -> str:
    u = url.rstrip("/")
    if not u.endswith(("/", "")):
        return u
    return u or "/"


def _path_segments(path: str) -> list[str]:
    """Return non-empty path segments, lowercased."""
    return [s.lower() for s in (path or "/").strip("/").split("/") if s]


def _infer_section_key(path: str) -> str:
    segments = _path_segments(path)
    if not segments:
        return "main"
    for seg in segments:
        if seg in _OPTIONAL_SEGMENTS:
            return "optional"
    for seg in segments:
        if seg not in _LOCALE_LIKE and len(seg) <= 30 and seg.replace("-", "").isalnum():
            return seg
    return "main"


def _section_key_to_title(key: str, default_section: str) -> str:
    """Turn section key into H2 title: main -> default_section, careers -> Careers, optional -> Optional."""
    if key == "main":
        return default_section
    if key == "optional":
        return "Optional"
    return key.replace("-", " ").title()


def _section_for_url(url: str, options: GeneratorOptions) -> str:
    parsed = urlparse(url)
    path = (parsed.path or "/").lower()

    if options.auto_sections:
        key = _infer_section_key(path)
        return _section_key_to_title(key, options.default_section)

    if options.optional_paths:
        for prefix in options.optional_paths:
            if path.startswith(prefix.rstrip("/").lower()) or path == prefix.lower():
                return "Optional"
    segments = _path_segments(path)
    rules = options.section_rules or []
    for prefix, section_name in rules:
        p = prefix.lower().rstrip("/")
        if p and (path.startswith(p + "/") or path == p):
            return section_name
    seg_rules = options.segment_rules or []
    for segment, section_name in seg_rules:
        if segment.lower() in segments:
            return section_name
    return options.default_section


def _find_homepage(pages: list, base_url: str | None) -> tuple[str, str]:
    """
    Find homepage title and summary from pages.
    Returns (title, summary). Uses base_url to pick the homepage; else origin of first page.
    """
    if not pages:
        return "Site", ""
    if base_url:
        base = base_url.rstrip("/")
    else:
        parsed = urlparse(getattr(pages[0], "url", "") or "")
        base = f"{parsed.scheme or 'https'}://{parsed.netloc}"
    homepage = None
    for p in pages:
        u = getattr(p, "url", "") or ""
        n = _normalize_for_compare(u)
        if n == base or n == base + "/":
            homepage = p
            break
    if not homepage:
        homepage = pages[0]
    title = (getattr(homepage, "title", None) or "").strip() or "Site"
    summary = (getattr(homepage, "description", None) or "").strip()
    return title, summary


def generate_llms_txt(pages: list, options: GeneratorOptions | None = None) -> str:
    opts = options or GeneratorOptions()
    logger.info("Generate starting: %d pages", len(pages))
    if opts.site_name is not None:
        title = opts.site_name.strip() or "Site"
        summary = (opts.summary or "").strip()
    else:
        title, summary = _find_homepage(pages, opts.base_url)

    if opts.summary is not None:
        summary = opts.summary.strip()

    groups: dict[str, list] = defaultdict(list)
    section_order: list[str] = []
    for p in pages:
        url = getattr(p, "url", "")
        section = _section_for_url(url, opts)
        if section not in section_order:
            section_order.append(section)
        groups[section].append(p)

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    if summary:
        lines.append(f"> {summary}")
        lines.append("")
    main_label = opts.default_section
    ordered = [s for s in section_order if s != "Optional"]
    if main_label in ordered:
        ordered.remove(main_label)
        ordered.insert(0, main_label)
    ordered.sort(key=lambda s: (0 if s == main_label else 1, s.lower()))
    if "Optional" in section_order:
        ordered.append("Optional")
    for section in ordered:
        items = groups.get(section, [])
        if not items:
            continue
        lines.append(f"## {section}")
        lines.append("")
        for p in items:
            url = getattr(p, "url", "")
            t = (getattr(p, "title", None) or "").strip() or url
            desc = (getattr(p, "description", None) or "").strip()
            if desc:
                lines.append(f"- [{t}]({url}): {_escape_md(desc)}")
            else:
                lines.append(f"- [{t}]({url})")
        lines.append("")

    out = "\n".join(lines).rstrip() + "\n"
    logger.info("Generate finished: %d sections, %d chars", len(ordered), len(out))
    return out
