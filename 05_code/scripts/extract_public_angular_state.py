"""Extract two observed public list responses already embedded in saved Angular HTML.

This reads local HTML obtained without credentials. It does not call any API or
infer that the listed items are currently accessible, free, or purchasable.
"""
import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

SOURCES = {
    'vocabulary': ('/api/public/courses/glossary/list', 'glossary'),
    'calculators': ('/api/public/courses/calculatorpage/list', 'calculator'),
}


class StateParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.chunks = []
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('id') == 'ng-state':
            self.count += 1
            self.inside = True

    def handle_data(self, data):
        if self.inside:
            self.chunks.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.inside:
            self.inside = False


def extract(html, section, source_url, observed_at):
    if section not in SOURCES:
        raise ValueError('Unsupported section')
    parsed = urlsplit(source_url)
    if parsed.scheme != 'https' or parsed.netloc != 'kurs.alfabank.ru' or parsed.path != f'/{section}/':
        raise ValueError('Source must be the exact public section URL')
    parser = StateParser()
    parser.feed(html)
    if parser.count != 1:
        raise ValueError('Expected exactly one Angular state script')
    state = json.loads(''.join(parser.chunks))
    if not isinstance(state, dict):
        raise ValueError('Invalid state')
    endpoint, kind = SOURCES[section]
    lists, reported_counts = [], []
    for value in state.values():
        if not isinstance(value, dict) or not isinstance(value.get('u'), str):
            continue
        url = urlsplit(value['u'])
        if url.scheme != 'https' or url.netloc != 'kurs.alfabank.ru':
            continue
        if url.path == endpoint and isinstance(value.get('b'), list):
            lists.append(value['b'])
        if url.path == endpoint + '/count' and type(value.get('b')) is int:
            reported_counts.append(value['b'])
    if len(lists) != 1:
        raise ValueError('Expected exactly one observed list response')
    if len(set(reported_counts)) > 1:
        raise ValueError('Conflicting count responses')
    rows, seen = [], set()
    for item in lists[0]:
        if not isinstance(item, dict):
            raise ValueError('List item must be an object')
        item_id, title, slug = item.get('id'), item.get('title'), item.get('url')
        if any(not isinstance(v, str) or not v.strip() for v in (item_id, title, slug)):
            raise ValueError('Missing item id, title or slug')
        if item_id in seen:
            raise ValueError('Duplicate item id')
        seen.add(item_id)
        description = item.get('description')
        if description is not None and not isinstance(description, str):
            raise ValueError('Description is not text')
        rows.append({'entity_key': f'{kind}:{item_id}', 'kind': kind, 'source_id': item_id,
                     'title': title, 'description': description, 'source_slug': slug,
                     'source_published_raw': item.get('published'),
                     'source_modified_raw': item.get('modified'),
                     'source_status_id_raw': item.get('statusId'),
                     'source_noindex_raw': item.get('noIndex'),
                     'access_type': 'unknown', 'price_status': 'unknown',
                     'canonical_url': None, 'source_page': source_url,
                     'embedded_endpoint': endpoint, 'observed_at': observed_at})
    report = {'source_page': source_url, 'embedded_endpoint': endpoint, 'observed_at': observed_at,
              'item_count': len(rows), 'reported_count': reported_counts[0] if reported_counts else None,
              'list_matches_reported_count': len(rows) == reported_counts[0] if reported_counts else None,
              'missing_descriptions': sum(not (r['description'] or '').strip() for r in rows),
              'missing_publication_dates': sum(not r['source_published_raw'] for r in rows),
              'noindex_counts': dict(Counter(str(r['source_noindex_raw']) for r in rows)),
              'coverage_verified': False,
              'limitations': 'Public embedded list; not verified current publication, rights, price, canonical URL, or full platform coverage.'}
    return rows, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html', type=Path, required=True)
    parser.add_argument('--section', choices=SOURCES, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output must not exist')
    data = args.html.read_bytes()
    observed_at = datetime.fromtimestamp(args.html.stat().st_mtime, UTC).isoformat()
    rows, report = extract(data.decode('utf-8', errors='strict'), args.section,
                           f'https://kurs.alfabank.ru/{args.section}/', observed_at)
    args.output.mkdir(parents=True)
    (args.output / 'materials.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    report['html_sha256'] = hashlib.sha256(data).hexdigest()
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
