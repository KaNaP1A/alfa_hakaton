import hashlib
import json
import sqlite3
import ssl
import tempfile
import unittest
import urllib.error
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scripts import crawl_sitemap_metadata as base
from scripts import crawl_sitemap_skip_unavailable as runner

ORIGIN = 'https://kurs.alfabank.ru'
ROBOTS = b'User-agent: *\nDisallow: /catalog\n'


class SkipUnavailableTests(unittest.TestCase):
    def test_individual_errors_and_global_restrictions(self):
        def error(status):
            return urllib.error.HTTPError(ORIGIN, status, 'example', {}, None)
        self.assertEqual(runner.classify(error(404)), ('skipped_http_404', False))
        self.assertEqual(runner.classify(error(403)), ('skipped_http_403', True))
        self.assertEqual(runner.classify(error(500)), ('skipped_http_500', True))
        self.assertEqual(runner.classify(error(429)), (None, True))
        self.assertEqual(runner.classify(error(503)), (None, True))
        self.assertEqual(runner.classify(TimeoutError('timed out')), ('skipped_timeout', True))
        self.assertEqual(runner.classify(urllib.error.URLError(ssl.SSLError('bad cert'))), (None, True))

    def test_reuses_recorded_404_and_continues_without_repeating_request(self):
        first = ORIGIN + '/articles/first/'
        second = ORIGIN + '/articles/second/'
        rows = [{'url': first, 'kind_hint': 'article', 'robots_allowed': True},
                {'url': second, 'kind_hint': 'article', 'robots_allowed': True}]
        seen = []

        def resumed_fetch(opener, url):
            seen.append(url)
            if url.endswith('/robots.txt'):
                return ROBOTS, 'text/plain'
            return b'<h1>Second</h1>', 'text/html'

        with tempfile.TemporaryDirectory() as temp:
            inventory = Path(temp) / 'inventory.jsonl'
            inventory.write_text(''.join(json.dumps(x) + '\n' for x in rows))
            output = Path(temp) / 'out'
            output.mkdir()
            with closing(sqlite3.connect(output / 'checkpoint.sqlite')) as db:
                base.create_frontier(db, rows, hashlib.sha256(inventory.read_bytes()).hexdigest(),
                                     hashlib.sha256(ROBOTS).hexdigest(),
                                     hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest())
                with db:
                    db.execute('INSERT INTO failures VALUES (?,?,?)',
                               (first, 'HTTPError: HTTP Error 404: Not Found', 'now'))
            with patch('scripts.crawl_sitemap_skip_unavailable.fetch', side_effect=resumed_fetch), patch('scripts.crawl_sitemap_skip_unavailable.time.sleep'), patch('scripts.crawl_sitemap_skip_unavailable.ssl.create_default_context'):
                report = runner.crawl(inventory, output, Path('fake'), max_pages=1)
            self.assertNotIn(first, seen)
            self.assertIn(second, seen)
            self.assertEqual(report['frontier']['skipped_http_404'], 1)
            self.assertEqual(report['frontier']['done'], 1)
            with closing(sqlite3.connect(output / 'checkpoint.sqlite')) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM failures').fetchone()[0], 1)

    def test_429_stops_and_keeps_page_pending(self):
        page = ORIGIN + '/articles/rate-limited/'

        def blocked_fetch(opener, url):
            if url.endswith('/robots.txt'):
                return ROBOTS, 'text/plain'
            raise urllib.error.HTTPError(url, 429, 'Rate limited', {}, None)

        with tempfile.TemporaryDirectory() as temp:
            inventory = Path(temp) / 'inventory.jsonl'
            inventory.write_text(json.dumps({'url': page, 'kind_hint': 'article', 'robots_allowed': True}) + '\n')
            output = Path(temp) / 'out'
            with patch('scripts.crawl_sitemap_skip_unavailable.fetch', side_effect=blocked_fetch), patch('scripts.crawl_sitemap_skip_unavailable.time.sleep'), patch('scripts.crawl_sitemap_skip_unavailable.ssl.create_default_context'):
                with self.assertRaises(urllib.error.HTTPError):
                    runner.crawl(inventory, output, Path('fake'), max_pages=1)
            with closing(sqlite3.connect(output / 'checkpoint.sqlite')) as db:
                self.assertEqual(db.execute('SELECT state FROM frontier').fetchone()[0], 'pending')
                self.assertEqual(db.execute('SELECT count(*) FROM failures').fetchone()[0], 1)

    def test_new_404_and_timeout_do_not_stop_other_cards(self):
        rows = [{'url': f'{ORIGIN}/articles/item-{i}/', 'kind_hint': 'article',
                 'robots_allowed': True} for i in range(3)]

        def flaky_fetch(opener, url):
            if url.endswith('/robots.txt'):
                return ROBOTS, 'text/plain'
            if url == rows[0]['url']:
                raise urllib.error.HTTPError(url, 404, 'Not Found', {}, None)
            if url == rows[1]['url']:
                raise TimeoutError('timed out')
            return b'<h1>Available</h1>', 'text/html'

        with tempfile.TemporaryDirectory() as temp:
            inventory = Path(temp) / 'inventory.jsonl'
            inventory.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            output = Path(temp) / 'out'
            with patch('scripts.crawl_sitemap_skip_unavailable.fetch', side_effect=flaky_fetch), patch('scripts.crawl_sitemap_skip_unavailable.time.sleep'), patch('scripts.crawl_sitemap_skip_unavailable.ssl.create_default_context'):
                report = runner.crawl(inventory, output, Path('fake'), max_pages=3)
            self.assertEqual(report['frontier']['skipped_http_404'], 1)
            self.assertEqual(report['frontier']['skipped_timeout'], 1)
            self.assertEqual(report['frontier']['done'], 1)

    def test_repeated_denied_pages_stop_to_avoid_sitewide_block(self):
        rows = [{'url': f'{ORIGIN}/articles/item-{i}/', 'kind_hint': 'article',
                 'robots_allowed': True} for i in range(3)]

        def denied_fetch(opener, url):
            if url.endswith('/robots.txt'):
                return ROBOTS, 'text/plain'
            raise urllib.error.HTTPError(url, 403, 'Forbidden', {}, None)

        with tempfile.TemporaryDirectory() as temp:
            inventory = Path(temp) / 'inventory.jsonl'
            inventory.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            output = Path(temp) / 'out'
            with patch('scripts.crawl_sitemap_skip_unavailable.fetch', side_effect=denied_fetch), patch('scripts.crawl_sitemap_skip_unavailable.time.sleep'), patch('scripts.crawl_sitemap_skip_unavailable.ssl.create_default_context'):
                with self.assertRaises(urllib.error.HTTPError):
                    runner.crawl(inventory, output, Path('fake'), max_pages=3)
            with closing(sqlite3.connect(output / 'checkpoint.sqlite')) as db:
                states = dict(db.execute('SELECT state, count(*) FROM frontier GROUP BY state'))
            self.assertEqual(states, {'skipped_http_403': 2, 'pending': 1})

    def test_many_missing_pages_do_not_stop_collection(self):
        rows = [{'url': f'{ORIGIN}/articles/missing-{i}/', 'kind_hint': 'article',
                 'robots_allowed': True} for i in range(4)]
        rows.append({'url': f'{ORIGIN}/articles/available/', 'kind_hint': 'article',
                     'robots_allowed': True})

        def missing_fetch(opener, url):
            if url.endswith('/robots.txt'):
                return ROBOTS, 'text/plain'
            if '/missing-' in url:
                raise urllib.error.HTTPError(url, 404, 'Not Found', {}, None)
            return b'<h1>Available</h1>', 'text/html'

        with tempfile.TemporaryDirectory() as temp:
            inventory = Path(temp) / 'inventory.jsonl'
            inventory.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            output = Path(temp) / 'out'
            with patch('scripts.crawl_sitemap_skip_unavailable.fetch', side_effect=missing_fetch), patch('scripts.crawl_sitemap_skip_unavailable.time.sleep'), patch('scripts.crawl_sitemap_skip_unavailable.ssl.create_default_context'):
                report = runner.crawl(inventory, output, Path('fake'), max_pages=5)
            self.assertEqual(report['frontier'], {'done': 1, 'skipped_http_404': 4})


    def test_oversized_page_skipped(self):
        rows = [{'url': f'{ORIGIN}/articles/item-{i}/', 'kind_hint': 'article',
                 'robots_allowed': True} for i in range(2)]

        def fake_fetch(opener, url):
            if url.endswith('/robots.txt'):
                return ROBOTS, 'text/plain'
            if url == rows[0]['url']:
                raise runner.ResponseTooLarge('Response too large')
            return b'<h1>Available</h1>', 'text/html'

        with tempfile.TemporaryDirectory() as temp:
            inventory = Path(temp) / 'inventory.jsonl'
            inventory.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            output = Path(temp) / 'out'
            with patch('scripts.crawl_sitemap_skip_unavailable.fetch', side_effect=fake_fetch), patch('scripts.crawl_sitemap_skip_unavailable.time.sleep'), patch('scripts.crawl_sitemap_skip_unavailable.ssl.create_default_context'):
                report = runner.crawl(inventory, output, Path('fake'), max_pages=2)
            self.assertEqual(report['frontier'], {'done': 1, 'skipped_too_large': 1})


if __name__ == '__main__':
    unittest.main()
