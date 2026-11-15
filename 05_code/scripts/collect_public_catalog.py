"""Collect publicly reachable Alfa-Kurs page metadata, subject to robots.txt.

Metadata only, with verified HTTPS; no authentication, paid content or bypasses.
Coverage is unknown unless independently verified against a catalog/source of truth.
"""
import argparse
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, deque
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from protego import Protego

ORIGIN = 'https://kurs.alfabank.ru'
AGENT = 'AlfaRecoResearchBot/1.0'
KINDS = {'courses': 'course', 'articles': 'article', 'webinars': 'webinar',
         'podcasts': 'podcast', 'documents': 'document', 'vocabulary': 'glossary',
         'calculators': 'calculator'}


def normal_url(url):
    parsed = urllib.parse.urlsplit(urllib.parse.urljoin(ORIGIN, url))
    if parsed.scheme != 'https' or parsed.netloc != 'kurs.alfabank.ru':
        return None
    # Pagination links observed on pages are retained, but tracking and arbitrary filters are not.
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if k in {'page', 'p', 'offset'} and v.isdigit()]
    return urllib.parse.urlunsplit(('https', parsed.netloc, parsed.path or '/',
                                    urllib.parse.urlencode(query), ''))


def should_visit(url):
    path = urllib.parse.urlsplit(url).path
    parts = [p for p in path.split('/') if p]
    return path == '/' or path.endswith('.xml') or (bool(parts) and parts[0] in KINDS and len(parts) <= 2)


def page_kind(url):
    parts = [p for p in urllib.parse.urlsplit(url).path.split('/') if p]
    return KINDS.get(parts[0]) if len(parts) == 2 else None


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.metadata = {}
        self.h1 = []
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == 'a' and attr.get('href'):
            self.links.append(attr['href'])
        elif tag == 'meta':
            key = attr.get('property') or attr.get('name') or ''
            if key in {'og:title', 'og:description', 'description', 'product:price:amount',
                       'product:price:currency'} and attr.get('content'):
                self.metadata[key] = attr['content']
        elif tag == 'h1':
            self._in_h1 = True

    def handle_endtag(self, tag):
        if tag == 'h1':
            self._in_h1 = False

    def handle_data(self, data):
        if self._in_h1:
            self.h1.append(data)

    def record(self, url, observed_at):
        kind = page_kind(url)
        title = ' '.join(' '.join(self.h1).split()) or self.metadata.get('og:title', '').strip()
        if not kind or not title:
            return None
        return {'url': url, 'kind': kind, 'title': title,
                'description': self.metadata.get('og:description') or self.metadata.get('description'),
                # Raw metadata is evidence, not verified actual price or current entitlement.
                'price_raw_meta': self.metadata.get('product:price:amount'),
                'currency_raw_meta': self.metadata.get('product:price:currency'),
                'access': 'unknown', 'price_status': 'unknown', 'observed_at': observed_at,
                'source': 'public_html_metadata', 'current_purchase_verified': False}


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    policy = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if normal_url(newurl) is None:
            raise urllib.error.HTTPError(newurl, code, 'Cross-origin redirect blocked', headers, fp)
        if self.policy is not None and not self.policy.can_fetch(newurl, AGENT):
            raise urllib.error.HTTPError(newurl, code, 'Redirect blocked by robots.txt', headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ResponseTooLarge(ValueError):
    """A single page exceeded the configured response size limit."""


def fetch(opener, url, max_bytes=4_000_000):
    request = urllib.request.Request(url, headers={'User-Agent': AGENT, 'Accept': 'text/html, application/xml, text/plain;q=0.9'})
    with opener.open(request, timeout=20) as response:
        if normal_url(response.geturl()) is None:
            raise ValueError('Response left permitted origin')
        content = response.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ResponseTooLarge('Response too large')
        return content, response.headers.get_content_type()


def sitemap_urls(content):
    root = ElementTree.fromstring(content)
    return [node.text.strip() for node in root.iter() if node.tag.endswith('}loc') and node.text]


def collect(output, max_pages=3000, delay=1.0, ca_file=None):
    if max_pages < 1 or delay < 1.0:
        raise ValueError('Require max_pages >= 1 and delay >= 1 second')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output must be a new or empty directory')
    redirect = SameHostRedirect()
    context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
    opener = urllib.request.build_opener(redirect, urllib.request.HTTPSHandler(context=context))
    # Fail closed on connection/SSL/HTTP errors rather than guessing crawl permissions.
    robots, _ = fetch(opener, ORIGIN + '/robots.txt')
    rp = Protego.parse(robots.decode('utf-8', errors='strict'))
    redirect.policy = rp
    delay = max(delay, rp.crawl_delay(AGENT) or rp.crawl_delay('*') or 0)
    rate = rp.request_rate(AGENT) or rp.request_rate('*')
    if rate and rate.requests > 0:
        delay = max(delay, rate.seconds / rate.requests)
    initial = [ORIGIN + '/', *[f'{ORIGIN}/{section}/' for section in KINDS]]
    initial += list(rp.sitemaps)
    queue = deque(url for raw in initial if (url := normal_url(raw)) and should_visit(url))
    seen, records, errors, skipped = set(), [], Counter(), Counter()
    sitemaps = 0
    while queue and len(seen) < max_pages:
        url = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        if not rp.can_fetch(url, AGENT):
            skipped['robots_disallowed'] += 1
            continue
        time.sleep(delay)
        try:
            body, content_type = fetch(opener, url)
            if 'xml' in content_type or urllib.parse.urlsplit(url).path.endswith('.xml'):
                sitemaps += 1
                queue.extend(url for raw in sitemap_urls(body)
                             if (url := normal_url(raw)) and should_visit(url))
                continue
            if content_type != 'text/html':
                skipped['not_html'] += 1
                continue
            parser = MetadataParser()
            parser.feed(body.decode('utf-8', errors='replace'))
            record = parser.record(url, datetime.now(UTC).isoformat())
            if record:
                records.append(record)
            for link in parser.links:
                clean = normal_url(link)
                if clean and should_visit(clean):
                    queue.append(clean)
        except urllib.error.HTTPError as error:
            errors[f'http_{error.code}'] += 1
            if error.code in {401, 403, 429}:
                break
        except (urllib.error.URLError, OSError, ValueError, ElementTree.ParseError) as error:
            errors[type(error).__name__] += 1
            break
    output.mkdir(parents=True, exist_ok=True)
    (output / 'materials.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records), encoding='utf-8')
    report = {'fetched_or_considered_urls': len(seen), 'records': len(records),
              'by_kind': dict(Counter(r['kind'] for r in records)), 'errors': dict(errors),
              'skipped': dict(skipped), 'sitemaps_processed': sitemaps, 'remaining_queue': len(queue),
              'stopped_at_page_limit': bool(queue and len(seen) >= max_pages),
              'coverage_verified': False,
              'note': 'Public HTML metadata only. Missing JS/API content, access and prices are unknown; do not claim complete catalog.'}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-pages', type=int, default=3000)
    parser.add_argument('--delay', type=float, default=1.0)
    parser.add_argument('--ca-file', type=Path, help='PEM trust anchor for this process only')
    args = parser.parse_args()
    print(json.dumps(collect(args.output, args.max_pages, args.delay, args.ca_file), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
