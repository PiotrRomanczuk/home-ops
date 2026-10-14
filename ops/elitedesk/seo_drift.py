"""seo_drift.py — crawl the site's own sitemap and apply deterministic rules.

What the HTML *actually* says (title, description, canonical, robots, JSON-LD,
CTA + internal-link coverage, word count) is snapshotted daily; rules turn it
into findings keyed by (path, rule). Pure parts (parse_page, rules) are tested;
fetch_* is the only network code.
"""
from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

UA = 'home-ops seo-drift/1 (+https://github.com/PiotrRomanczuk/home-ops)'
CTA_HINTS = ('tel:', '/rezerwacja', '#rezerwacja', '/cennik', '#cennik', 'cal.com', '#kontakt', 'mailto:')
TITLE_RANGE, DESC_RANGE, MIN_WORDS = (30, 65), (70, 160), 250


class _Page(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__()
        self.base, self.host = base, urlparse(base).netloc
        self.title = self.description = self.canonical = self.robots = self.h1 = None
        self.has_jsonld, self.cta, self.internal, self.words = False, 0, 0, 0
        self._in: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or '') for k, v in attrs}
        if tag == 'title':
            self._in = 'title'
        elif tag == 'h1' and self.h1 is None:
            self._in = 'h1'
        elif tag in ('script', 'style'):
            self._in = 'skip'
            if tag == 'script' and a.get('type') == 'application/ld+json':
                self.has_jsonld = True
        elif tag == 'meta':
            name = a.get('name', '').lower()
            if name == 'description':
                self.description = a.get('content')
            elif name == 'robots':
                self.robots = a.get('content')
        elif tag == 'link' and a.get('rel', '').lower() == 'canonical':
            self.canonical = a.get('href')
        elif tag == 'a':
            href = a.get('href', '')
            if any(h in href for h in CTA_HINTS):
                self.cta += 1
            if href.startswith('/') or urlparse(href).netloc == self.host:
                self.internal += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ('title', 'h1', 'script', 'style'):
            self._in = None

    def handle_data(self, data: str) -> None:
        if self._in == 'title':
            self.title = (self.title or '') + data.strip()
        elif self._in == 'h1':
            self.h1 = (self.h1 or '') + data.strip()
        elif self._in != 'skip':
            self._text.append(data)

    def result(self) -> dict[str, Any]:
        words = len(re.findall(r'\w+', ' '.join(self._text)))
        return {'title': self.title, 'description': self.description, 'canonical': self.canonical,
                'robots': self.robots, 'has_jsonld': self.has_jsonld, 'words': words,
                'cta_links': self.cta, 'internal_links': self.internal, 'h1': self.h1}


def parse_page(html: str, url: str) -> dict[str, Any]:
    p = _Page(url)
    p.feed(html)
    return p.result()


def fetch(url: str, timeout: float = 20.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, ''
    except Exception:  # noqa: BLE001 — unreachable = status 0, a finding, not a crash
        return 0, ''


def sitemap_paths(xml: str, base: str) -> list[str]:
    host = urlparse(base).netloc
    return [urlparse(u).path or '/' for u in re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', xml)
            if urlparse(u).netloc == host]


def snapshot_site(base: str) -> list[dict[str, Any]]:
    _, xml = fetch(urljoin(base, '/sitemap.xml'))
    rows = []
    for path in sitemap_paths(xml, base) or ['/']:
        status, html = fetch(urljoin(base, path))
        rows.append({'path': path, 'status_code': status, **parse_page(html, urljoin(base, path))})
    return rows


def rules(snap: dict[str, Any], prev: dict[str, Any] | None, base: str) -> list[dict[str, str]]:
    """Findings for one page: [{rule, severity, detail}]. Deterministic, no LLM."""
    out: list[dict[str, str]] = []
    add = lambda rule, sev, detail: out.append({'rule': rule, 'severity': sev, 'detail': detail})  # noqa: E731
    path = snap['path']
    if snap['status_code'] != 200:
        add('http-status', 'error', f'HTTP {snap["status_code"]} dla {path}')
        return out
    t, d = snap.get('title') or '', snap.get('description') or ''
    if not (TITLE_RANGE[0] <= len(t) <= TITLE_RANGE[1]):
        add('title-length', 'warn', f'title {len(t)} znaków: „{t[:70]}”')
    if not (DESC_RANGE[0] <= len(d) <= DESC_RANGE[1]):
        add('description-length', 'warn', f'description {len(d)} znaków')
    if snap.get('canonical') and urlparse(snap['canonical']).path.rstrip('/') != path.rstrip('/'):
        add('canonical-mismatch', 'error', f'canonical {snap["canonical"]} ≠ {path}')
    if 'noindex' in (snap.get('robots') or '').lower():
        add('noindex-in-sitemap', 'error', 'strona w sitemapie ma meta robots noindex')
    if not snap.get('has_jsonld'):
        add('missing-jsonld', 'warn', 'brak JSON-LD')
    if snap.get('cta_links', 0) == 0:
        add('no-cta', 'warn', 'strona bez linku do cennika / rezerwacji / telefonu')
    if snap.get('words', 0) < MIN_WORDS and path != '/':
        add('thin-content', 'warn', f'tylko {snap["words"]} słów (próg {MIN_WORDS})')
    if prev and prev.get('title') and prev['title'] != t:
        add('title-changed', 'info', f'title zmienił się: „{prev["title"][:50]}” → „{t[:50]}”')
    return out
