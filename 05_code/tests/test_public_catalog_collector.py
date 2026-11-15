import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from protego import Protego

from scripts.collect_public_catalog import (
    MetadataParser,
    SameHostRedirect,
    collect,
    normal_url,
    page_kind,
    should_visit,
    sitemap_urls,
)


class CollectorTests(unittest.TestCase):
    def test_origin_and_public_navigation_only(self):
        self.assertEqual(normal_url('/courses/?page=2&token=secret'), 'https://kurs.alfabank.ru/courses/?page=2')
        self.assertIsNone(normal_url('https://elsewhere.example/courses/x/'))
        self.assertIsNone(normal_url('http://kurs.alfabank.ru/courses/'))
        self.assertEqual(page_kind('https://kurs.alfabank.ru/courses/example/'), 'course')
        self.assertFalse(should_visit('https://kurs.alfabank.ru/courses/example/lesson/1/'))
        self.assertFalse(should_visit('https://kurs.alfabank.ru/login/'))
        self.assertTrue(should_visit('https://kurs.alfabank.ru/api/public/courses/sitemap/sitemap.xml'))

    def test_robots_wildcards_and_precedence(self):
        parser = Protego.parse("""User-agent: *
Disallow: /catalog
Disallow: /*(modal:auth)
Disallow: /*(modal:document)
Disallow: /private/*$
Allow: /private/ok$
""")
        self.assertFalse(parser.can_fetch('https://kurs.alfabank.ru/catalog/', 'AlfaRecoResearchBot'))
        self.assertFalse(parser.can_fetch('https://kurs.alfabank.ru/courses/x/(modal:auth)', 'AlfaRecoResearchBot'))
        self.assertFalse(parser.can_fetch('https://kurs.alfabank.ru/courses/x/(modal:document)', 'AlfaRecoResearchBot'))
        self.assertTrue(parser.can_fetch('https://kurs.alfabank.ru/private/ok', 'AlfaRecoResearchBot'))
        self.assertFalse(parser.can_fetch('https://kurs.alfabank.ru/private/no', 'AlfaRecoResearchBot'))

    def test_redirect_cannot_bypass_origin_or_robots(self):
        redirect = SameHostRedirect()
        redirect.policy = Protego.parse('User-agent: *\nDisallow: /catalog\n')
        request = Request('https://kurs.alfabank.ru/courses/example/')
        for target in ('https://example.com/', 'https://kurs.alfabank.ru/catalog/'):
            with self.subTest(target=target), self.assertRaises(HTTPError):
                redirect.redirect_request(request, None, 302, 'Found', {}, target)

    def test_never_converts_price_metadata_to_verified_offer(self):
        parser = MetadataParser()
        parser.feed('<meta property="product:price:amount" content="3990"><h1>Тест</h1>')
        record = parser.record('https://kurs.alfabank.ru/courses/test/', '2026-11-15T00:00:00Z')
        self.assertEqual(record['price_raw_meta'], '3990')
        self.assertEqual(record['price_status'], 'unknown')
        self.assertFalse(record['current_purchase_verified'])
        self.assertIsNone(parser.record('https://kurs.alfabank.ru/courses/', 'now'))

    def test_unavailable_robots_is_failure_not_permission_to_crawl(self):
        with tempfile.TemporaryDirectory() as temp, patch('scripts.collect_public_catalog.fetch', side_effect=URLError('SSL')):
            path = Path(temp) / 'output'
            with self.assertRaises(URLError):
                collect(path)
            self.assertFalse(path.exists())

    def test_sitemap_urls(self):
        xml = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://kurs.alfabank.ru/courses/a/</loc></url></urlset>'
        self.assertEqual(sitemap_urls(xml), ['https://kurs.alfabank.ru/courses/a/'])


if __name__ == '__main__':
    unittest.main()
