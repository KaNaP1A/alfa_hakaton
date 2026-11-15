import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scripts.crawl_sitemap_metadata import NoItemRedirect, crawl, parse_metadata, valid_item

ORIGIN = 'https://kurs.alfabank.ru'
ROBOTS = b'User-agent: *\nDisallow: /catalog\n'


def html(kind, slug, item_id='123'):
    data = {'a': {'u': f'{ORIGIN}/api/public/courses/{kind}/list',
                  'b': [{'id': item_id, 'url': slug, 'title': 'Пример', 'description': 'Описание',
                         'users': [{'secret': 'NEVER_STORE'}], 'statusId': 'source-status'}]}}
    return '<html><script id="ng-state" type="application/json">' + json.dumps(data) + '</script></html>'


class SitemapMetadataTests(unittest.TestCase):
    def test_only_item_urls_and_allowlisted_metadata(self):
        url = ORIGIN + '/articles/example/'
        record = parse_metadata(html('article', 'example'), url, 'article', 'now')
        self.assertEqual(record['entity_key'], 'article:123')
        self.assertEqual(record['access_type'], 'unknown')
        self.assertEqual(record['price_status'], 'unknown')
        self.assertNotIn('NEVER_STORE', json.dumps(record))
        self.assertFalse(valid_item(ORIGIN + '/courses/x/lesson/1/', 'course'))
        self.assertFalse(valid_item('https://evil.example/articles/example/', 'article'))
        self.assertFalse(valid_item(url + '?token=secret', 'article'))

    def test_conflicting_structured_ids_fail(self):
        item = {'u': ORIGIN + '/api/public/courses/article/list',
                'b': [{'id': 'a', 'url': 'example', 'title': 'A'},
                      {'id': 'b', 'url': 'example', 'title': 'B'}]}
        body = '<script id="ng-state">' + json.dumps({'a': item}) + '</script>'
        with self.assertRaises(ValueError):
            parse_metadata(body, ORIGIN + '/articles/example/', 'article', 'now')

    def test_checkpoint_resume_and_changed_robots(self):
        rows = [{'url': ORIGIN + '/articles/example/', 'kind_hint': 'article', 'robots_allowed': True},
                {'url': ORIGIN + '/courses/demo/', 'kind_hint': 'course', 'robots_allowed': True},
                {'url': ORIGIN + '/courses/demo/lesson/1/', 'kind_hint': 'lesson_url', 'robots_allowed': True}]
        visited = []

        def fake_fetch(opener, url):
            visited.append(url)
            if url.endswith('/robots.txt'):
                return ROBOTS, 'text/plain'
            if '/articles/' in url:
                return html('article', 'example').encode(), 'text/html'
            return b'<html><h1>Course</h1></html>', 'text/html'

        with tempfile.TemporaryDirectory() as temp:
            inventory = Path(temp) / 'inventory.jsonl'
            inventory.write_text(''.join(json.dumps(r) + '\n' for r in rows))
            output = Path(temp) / 'out'
            with patch('scripts.crawl_sitemap_metadata.fetch', side_effect=fake_fetch), patch('scripts.crawl_sitemap_metadata.time.sleep'), patch('scripts.crawl_sitemap_metadata.ssl.create_default_context'):
                first = crawl(inventory, output, Path('fake-ca'), max_pages=1)
                second = crawl(inventory, output, Path('fake-ca'), max_pages=1)
            self.assertEqual(first['extracted'], 1)
            self.assertEqual(second['extracted'], 2)
            self.assertEqual(len((output / 'materials.jsonl').read_text().splitlines()), 2)
            self.assertFalse(any('/lesson/' in url for url in visited))
            with closing(sqlite3.connect(output / 'checkpoint.sqlite')) as db:
                self.assertEqual(db.execute('select count(*) from frontier').fetchone()[0], 2)
            with patch('scripts.crawl_sitemap_metadata.fetch', return_value=(b'User-agent: *\nDisallow: /\n', 'text/plain')), patch('scripts.crawl_sitemap_metadata.ssl.create_default_context'):
                with self.assertRaises(ValueError):
                    crawl(inventory, output, Path('fake-ca'), max_pages=1)

    def test_item_redirect_never_followed(self):
        from urllib.error import HTTPError
        from urllib.request import Request

        with self.assertRaises(HTTPError):
            NoItemRedirect().redirect_request(Request(ORIGIN + '/articles/x/'), None, 301, 'Moved', {}, ORIGIN + '/catalog')


if __name__ == '__main__':
    unittest.main()
