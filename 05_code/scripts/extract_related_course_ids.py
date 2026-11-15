"""Extract cautious course-ID candidates from already-saved public page metadata.

Does not request an API or assert current rights, prices, or final backend identity.
"""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import UUID

if __package__:
    from scripts.extract_public_angular_state import StateParser
else:
    from extract_public_angular_state import StateParser


def extract(samples, sitemap_rows):
    by_slug = defaultdict(set)
    for row in sitemap_rows:
        if row.get('kind_hint') != 'course' or row.get('robots_allowed') is not True:
            continue
        url = row.get('url', '')
        parsed = urlsplit(url)
        parts = [p for p in parsed.path.split('/') if p]
        if parsed.scheme == 'https' and parsed.netloc == 'kurs.alfabank.ru' and len(parts) == 2 and parts[0] == 'courses' and not parsed.query:
            by_slug[unquote(parts[1]).casefold()].add(url)
    evidence = defaultdict(list)
    errors = Counter()
    for source_page, html in samples:
        parser = StateParser()
        parser.feed(html)
        if parser.count != 1:
            errors['missing_or_multiple_state'] += 1
            continue
        state = json.loads(''.join(parser.chunks))
        for response in state.values():
            if not isinstance(response, dict) or not isinstance(response.get('u'), str):
                continue
            p = urlsplit(response['u'])
            if p.scheme != 'https' or p.netloc != 'kurs.alfabank.ru' or p.path != '/api/public/courses/list':
                continue
            body = response.get('b')
            if not isinstance(body, list):
                continue
            for item in body:
                if not isinstance(item, dict):
                    continue
                item_id, slug, title = item.get('id'), item.get('url'), item.get('title')
                if not isinstance(item_id, str) or not isinstance(slug, str) or not slug or not isinstance(title, str):
                    errors['missing_fields'] += 1
                    continue
                try:
                    UUID(item_id)
                except ValueError:
                    errors['invalid_id'] += 1
                    continue
                matches = by_slug.get(unquote(slug).strip('/').casefold(), set())
                if len(matches) != 1:
                    errors['ambiguous_or_missing_slug'] += 1
                    continue
                candidate = {'source_id': item_id, 'title': title, 'source_page': source_page,
                             'embedded_endpoint': p.path, 'source_is_paid_raw': item.get('isPaid'),
                             'source_is_public_raw': item.get('isPublic'),
                             'source_has_subscriptions_raw': item.get('hasSubscriptions')}
                evidence[next(iter(matches))].append(candidate)
    rows = []
    for course_url, candidates in sorted(evidence.items()):
        ids = {item['source_id'] for item in candidates}
        if len(ids) != 1:
            errors['conflicting_ids'] += 1
            continue
        rows.append({'course_url': course_url, 'source_id': next(iter(ids)),
                     'evidence': candidates, 'backend_identity_verified': False,
                     'current_price_verified': False, 'current_access_verified': False})
    urls_by_id = defaultdict(set)
    for row in rows:
        urls_by_id[row['source_id']].add(row['course_url'])
    collision_ids = {item_id for item_id, urls in urls_by_id.items() if len(urls) > 1}
    errors['id_matches_multiple_urls'] += len(collision_ids)
    rows = [row for row in rows if row['source_id'] not in collision_ids]
    return rows, {'matched_course_urls': len(rows), 'errors': dict(errors),
                  'limitations': 'Candidate identity from explicit public metadata and exact slug; backend confirmation is required. Not an access or price check.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample-dir', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output must not exist')
    manifest = json.loads((args.sample_dir / 'manifest.json').read_text())
    samples = []
    for entry in manifest:
        path = args.sample_dir / f"{entry['kind']}.html"
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Sample hash mismatch')
        samples.append((entry['url'], data.decode('utf-8', 'strict')))
    sitemap = [json.loads(line) for line in args.inventory.read_text().splitlines() if line.strip()]
    rows, report = extract(samples, sitemap)
    args.output.mkdir(parents=True)
    (args.output / 'candidates.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
