"""Notify IndexNow once after a successful, publicly crawlable production release.

The verification key is public, not a credential. No search-engine account is
required. Receipt of a notification does not guarantee crawling or indexing.
"""

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET


ORIGIN = 'https://artprojectsro.cz'
HOST = 'artprojectsro.cz'
KEY_LOCATION = ORIGIN + '/indexnow-key.txt'
ENDPOINT = 'https://api.indexnow.org/indexnow'
KEY_FILE = Path(__file__).resolve().parents[1] / 'public' / 'indexnow-key.txt'
PAGES = ('/cs/', '/en/', '/ru/')
SITEMAP_NS = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
MAX_RESPONSE = 2 * 1024 * 1024


class PageMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.canonical = None
        self.noindex = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'link' and 'canonical' in attributes.get('rel', '').lower().split():
            self.canonical = attributes.get('href')
        if tag == 'meta' and attributes.get('name', '').lower() in (
                'robots', 'googlebot', 'bingbot', 'seznambot'):
            self.noindex |= bool(re.search(r'\bnoindex\b', attributes.get('content', ''), re.I))


def get(url):
    request = Request(url, headers={'User-Agent': 'ARTProject-Release-IndexNow/1.0'})
    with urlopen(request, timeout=15) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('Production verification must return HTTP 200 without redirects')
        body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise ValueError('Production verification response exceeds its size limit')
        return {key.lower(): value for key, value in response.headers.items()}, body


def canonical_urls(sitemap):
    root = ET.fromstring(sitemap)
    if root.tag != SITEMAP_NS + 'urlset':
        raise ValueError('Expected the production URL sitemap')
    urls = []
    for entry in root.findall(SITEMAP_NS + 'url'):
        url = (entry.findtext(SITEMAP_NS + 'loc') or '').strip()
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc != HOST or parsed.path not in PAGES
                or parsed.query or parsed.fragment or url != ORIGIN + parsed.path):
            raise ValueError('Sitemap contains a URL outside the canonical production pages')
        if url not in urls:
            urls.append(url)
    if set(urls) != {ORIGIN + page for page in PAGES}:
        raise ValueError('Sitemap must contain all three canonical language pages')
    return urls


def notify():
    key = KEY_FILE.read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'[0-9a-f]{32}', key):
        raise ValueError('The public IndexNow key must contain 32 hexadecimal characters')
    _, remote_key = get(KEY_LOCATION)
    if remote_key.decode('utf-8').strip() != key:
        raise ValueError('The deployed IndexNow key does not match this release')

    _, robots_body = get(ORIGIN + '/robots.txt')
    robots_text = robots_body.decode('utf-8')
    if re.search(r'^[ \t]*Disallow:[ \t]*/[ \t]*(?:#.*)?$', robots_text, re.M | re.I):
        raise ValueError('Production robots.txt still blocks the whole site')
    robots = RobotFileParser()
    robots.parse(robots_text.splitlines())
    _, sitemap = get(ORIGIN + '/sitemap.xml')
    urls = canonical_urls(sitemap)
    for url in urls:
        if any(not robots.can_fetch(agent, url) for agent in ('*', 'bingbot', 'Seznambot')):
            raise ValueError('Production robots.txt blocks a submitted page')
        headers, body = get(url)
        metadata = PageMetadata()
        metadata.feed(body.decode('utf-8'))
        if (metadata.noindex or re.search(r'\bnoindex\b', headers.get('x-robots-tag', ''), re.I)
                or metadata.canonical != url):
            raise ValueError('A submitted page is noindex or lacks its exact canonical URL')

    payload = {'host': HOST, 'key': key, 'keyLocation': KEY_LOCATION, 'urlList': urls}
    request = Request(ENDPOINT, data=json.dumps(payload).encode('utf-8'), method='POST',
                      headers={'Content-Type': 'application/json; charset=utf-8',
                               'User-Agent': 'ARTProject-Release-IndexNow/1.0'})
    with urlopen(request, timeout=15) as response:
        if response.status not in (200, 202):
            raise ValueError(f'IndexNow returned HTTP {response.status}')
        return len(urls), response.status


def main():
    try:
        count, status = notify()
        print(f'IndexNow received {count} canonical URLs (HTTP {status}); indexing is not guaranteed.')
    except (OSError, ValueError, ET.ParseError) as error:
        print(f'::warning::IndexNow notification skipped: {error}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
