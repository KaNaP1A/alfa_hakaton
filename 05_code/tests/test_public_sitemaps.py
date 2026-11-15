import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.discover_public_sitemaps import discover, parse_sitemap, url_kind

ORIGIN = 'https://kurs.alfabank.ru'
ROBOTS = b'User-agent: *\nDisallow: /catalog\nSitemap: https://kurs.alfabank.ru/sitemap.xml\n'
INDEX = b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://kurs.alfabank.ru/maps/courses.xml</loc></sitemap></sitemapindex>'
URLSET = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://kurs.alfabank.ru/courses/a/</loc></url><url><loc>https://kurs.alfabank.ru/catalog/x</loc></url><url><loc>https://kurs.alfabank.ru/courses/a/lesson/1/</loc></url><url><loc>https://evil.example/test/</loc></url></urlset>'


class SitemapTests(unittest.TestCase):
    def test_xml_and_url_classification(self):
        self.assertEqual(parse_sitemap(INDEX)[0], 'sitemapindex')
        self.assertEqual(url_kind(ORIGIN + '/courses/a/'), 'course')
        self.assertEqual(url_kind(ORIGIN + '/courses/a/lesson/1/'), 'lesson_url')
        with self.assertRaises(ValueError):
            parse_sitemap(b'<!DOCTYPE x [<!ENTITY x "bad">]><urlset/>')

    def test_only_fetches_robots_and_sitemaps_not_materials(self):
        fixtures = {ORIGIN + '/robots.txt': ROBOTS, ORIGIN + '/sitemap.xml': INDEX,
                    ORIGIN + '/maps/courses.xml': URLSET}
        visited = []

        def fake_fetch(opener, url):
            visited.append(url)
            return fixtures[url], 'application/xml'

        with tempfile.TemporaryDirectory() as temp, patch('scripts.discover_public_sitemaps.fetch', side_effect=fake_fetch), patch('scripts.discover_public_sitemaps.time.sleep'):
            output = Path(temp) / 'results'
            report = discover(output, None)
            rows = [json.loads(line) for line in (output / 'urls.jsonl').read_text().splitlines()]
        self.assertEqual(len(visited), 3)
        self.assertEqual(report['unique_urls'], 3)
        self.assertEqual(report['robots_disallowed_urls'], 1)
        self.assertEqual(report['skipped']['external_or_invalid_url'], 1)
        self.assertFalse(report['coverage_verified'])
        self.assertEqual({row['kind_hint'] for row in rows}, {'course', 'lesson_url', 'other_url'})


if __name__ == '__main__':
    unittest.main()
