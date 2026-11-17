from __future__ import annotations

import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import httpx

PAGES = {
    "media": "https://sites.google.com/view/bdixftpserverlist/media-ftp-servers",
    "livetv": "https://sites.google.com/view/bdixftpserverlist/live-tv-servers",
}

SOCIAL_HOSTS = {
    "www.facebook.com",
    "facebook.com",
    "m.facebook.com",
    "pastebin.com",
    "sites.google.com",
    "t.me",
    "telegram.me",
    "youtube.com",
    "www.youtube.com",
    "forms.gle",
    "bit.ly",
}


@dataclass(slots=True)
class Target:
    page: str
    provider: str
    url: str
    host: str
    scheme: str
    kind: str  # server | social


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str | None, str]] = []  # (heading, href)
        self._in_heading = False
        self._heading_buf: list[str] = []
        self._last_heading: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._in_heading = True
            self._heading_buf = []
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.items.append((self._last_heading, href))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self._in_heading:
            text = " ".join("".join(self._heading_buf).split())
            if text:
                self._last_heading = text
            self._in_heading = False
            self._heading_buf = []

    def handle_data(self, data: str) -> None:
        if self._in_heading:
            self._heading_buf.append(data)


def unwrap_google_url(href: str) -> str | None:
    href = href.replace("&amp;", "&")
    if "google.com/url" in href:
        parsed = urllib.parse.urlparse(href)
        q = urllib.parse.parse_qs(parsed.query).get("q")
        if q and q[0]:
            return q[0]
    # percent-encoded direct form sometimes appears
    if href.startswith("http%3A") or href.startswith("https%3A"):
        return urllib.parse.unquote(href)
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return None


def classify_kind(host: str) -> str:
    h = host.lower()
    if h in SOCIAL_HOSTS or h.endswith(".facebook.com"):
        return "social"
    return "server"


def parse_targets(html: str, page: str) -> list[Target]:
    parser = _PageParser()
    parser.feed(html)
    out: list[Target] = []
    seen: set[str] = set()
    for heading, href in parser.items:
        url = unwrap_google_url(href)
        if not url:
            continue
        p = urllib.parse.urlparse(url)
        if p.scheme not in {"http", "https"} or not p.hostname:
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        provider = (heading or "Unknown").strip()
        host = p.hostname
        out.append(
            Target(
                page=page,
                provider=provider,
                url=url,
                host=host,
                scheme=p.scheme,
                kind=classify_kind(host),
            )
        )
    return out


async def fetch_page(page: str, cache_dir: Path, refresh: bool = False) -> str:
    if page not in PAGES:
        raise ValueError(f"unknown page: {page}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{page}.html"
    if cache_file.exists() and not refresh:
        return cache_file.read_text(encoding="utf-8", errors="replace")
    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) bdix-check/0.1"},
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        r = await client.get(PAGES[page])
        r.raise_for_status()
        text = r.text
    cache_file.write_text(text, encoding="utf-8")
    return text


async def fetch_targets(
    pages: Iterable[str], cache_dir: Path, refresh: bool = False
) -> list[Target]:
    all_targets: list[Target] = []
    for page in pages:
        html = await fetch_page(page, cache_dir, refresh=refresh)
        all_targets.extend(parse_targets(html, page))
    return all_targets
