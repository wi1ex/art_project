import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError


spec = importlib.util.spec_from_file_location(
    'notify_search', Path(__file__).resolve().parents[1] / 'deploy' / 'notify_search.py')
search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search)
KEY = 'a123456789abcdefa123456789abcdef'
URLS = [search.ORIGIN + page for page in search.PAGES]


class Response:
    def __init__(self, url, body=b'', status=200, headers=None):
        self.url = url
        self.body = body
        self.status = status
        self.headers = headers or {}

    def geturl(self):
        return self.url

    def read(self, limit):
        return self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class SearchNotificationTests(unittest.TestCase):
    def setUp(self):
        self.responses = {
            search.KEY_LOCATION: Response(search.KEY_LOCATION, KEY.encode()),
            search.ORIGIN + '/robots.txt': Response(
                search.ORIGIN + '/robots.txt', b'User-agent: *\nAllow: /\nDisallow: /api/\n'),
            search.ORIGIN + '/sitemap.xml': Response(
                search.ORIGIN + '/sitemap.xml', self.sitemap(URLS)),
            search.ENDPOINT: Response(search.ENDPOINT, status=202),
        }
        for url in URLS:
            self.responses[url] = Response(url, self.page(url))
        self.requests = []
        self.key_patch = mock.patch.object(Path, 'read_text', return_value=KEY + '\n')
        self.network_patch = mock.patch.object(search, 'urlopen', side_effect=self.open)
        self.key_patch.start()
        self.network_patch.start()
        self.addCleanup(self.key_patch.stop)
        self.addCleanup(self.network_patch.stop)

    @staticmethod
    def sitemap(urls):
        return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + ''.join(f'<url><loc>{url}</loc></url>' for url in urls)
                + '</urlset>').encode()

    @staticmethod
    def page(url, extra=''):
        return f'<html><head><link rel="canonical" href="{url}">{extra}</head></html>'.encode()

    def open(self, request, timeout):
        self.requests.append(request)
        response = self.responses[request.full_url]
        if isinstance(response, Exception):
            raise response
        return response

    def posts(self):
        return [request for request in self.requests if request.get_method() == 'POST']

    def test_verified_canonical_payload_is_submitted_once(self):
        self.assertEqual(search.notify(), (3, 202))
        self.assertEqual(len(self.posts()), 1)
        request = self.posts()[0]
        self.assertEqual(request.full_url, 'https://api.indexnow.org/indexnow')
        self.assertEqual(json.loads(request.data), {
            'host': search.HOST, 'key': KEY, 'keyLocation': search.KEY_LOCATION, 'urlList': URLS})

    def test_mismatched_or_missing_deployed_key_never_submits(self):
        for response in (Response(search.KEY_LOCATION, b'wrong-key'),
                         HTTPError(search.KEY_LOCATION, 404, 'Not found', {}, None)):
            with self.subTest(response=response):
                self.responses[search.KEY_LOCATION] = response
                with self.assertRaises((ValueError, HTTPError)):
                    search.notify()
                self.assertEqual(self.posts(), [])

    def test_global_robots_block_never_submits(self):
        self.responses[search.ORIGIN + '/robots.txt'].body = b'User-agent: *\nDisallow: /\n'
        with self.assertRaisesRegex(ValueError, 'blocks the whole site'):
            search.notify()
        self.assertEqual(self.posts(), [])

    def test_noncanonical_sitemap_urls_never_submit(self):
        for invalid in ('https://other.example/cs/', search.ORIGIN + '/cs/?campaign=1',
                        search.ORIGIN + '/cs/#contact', search.ORIGIN + '/cs',
                        'http://artprojectsro.cz/cs/', search.ORIGIN + '/privacy-policy.pdf'):
            with self.subTest(invalid=invalid):
                self.responses[search.ORIGIN + '/sitemap.xml'].body = self.sitemap(
                    [invalid, *URLS[1:]])
                with self.assertRaises(ValueError):
                    search.notify()
                self.assertEqual(self.posts(), [])

    def test_page_noindex_or_canonical_mismatch_never_submits(self):
        url = URLS[0]
        cases = [
            Response(url, self.page(url, '<meta content="NOINDEX, follow" name="robots">')),
            Response(url, self.page(url), headers={'X-Robots-Tag': 'noindex'}),
            Response(url, self.page('https://other.example/cs/')),
            Response('https://other.example/cs/', self.page(url)),
        ]
        for response in cases:
            with self.subTest(response=response):
                self.responses[url] = response
                with self.assertRaises(ValueError):
                    search.notify()
                self.assertEqual(self.posts(), [])

    def test_api_error_warns_without_failing_release_or_retrying(self):
        self.responses[search.ENDPOINT] = HTTPError(
            search.ENDPOINT, 429, 'Too many requests', {}, None)
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            self.assertEqual(search.main(), 0)
        self.assertIn('::warning::IndexNow notification skipped:', output.getvalue())
        self.assertEqual(len(self.posts()), 1)

    def test_network_failure_warns_without_posting(self):
        self.responses[search.KEY_LOCATION] = URLError('Temporary DNS failure')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(search.main(), 0)
        self.assertEqual(self.posts(), [])


if __name__ == '__main__':
    unittest.main()
