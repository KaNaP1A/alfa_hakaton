"""Inventory public sitemap URLs, not material contents or prices.

Uses verified TLS and robots.txt; never accesses individual item or lesson pages.
Run against the owner-published sitemaps only. Coverage is not implied.
"""
import argparse
import hashlib
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, deque
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from protego import Protego

if __package__:
    from scripts.collect_public_catalog import (
        AGENT,
        KINDS,
        ORIGIN,
        SameHostRedirect,
        fetch,
        normal_url,
    )
else:
    from collect_public_catalog import AGENT, KINDS, ORIGIN, SameHostRedirect, fetch, normal_url


def parse_sitemap(body):
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise ValueError('DTD/entity is not accepted')
    root = ElementTree.fromstring(body)
    kind = root.tag.split('}')[-1]
    if kind not in {'sitemapindex', 'urlset'}:
        raise ValueError('Unknown sitemap type')
    rows = []
    for node in root:
        fields = {child.tag.split('}')[-1]: (child.text or '').strip() for child in node}
        if fields.get('loc'):
            rows.append({'url': fields['loc'], 'lastmod': fields.get('lastmod') or None})
    return kind, rows


def url_kind(url):
    parts = [p for p in urllib.parse.urlsplit(url).path.split('/') if p]
    if len(parts) >= 3 and parts[0] == 'courses' and parts[2] == 'lesson':
        return 'lesson_url'
    if len(parts) == 2 and parts[0] in KINDS:
        return KINDS[parts[0]]
    return 'other_url'


def discover(output, ca_file, delay=1.0, max_sitemaps=50):
    if delay < 1 or max_sitemaps < 1:
        raise ValueError('Require delay >= 1 second and max_sitemaps >= 1')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output must be new or empty')
    redirect = SameHostRedirect()
    context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
    opener = urllib.request.build_opener(redirect, urllib.request.HTTPSHandler(context=context))
    robots_bytes, _ = fetch(opener, ORIGIN + '/robots.txt')
    policy = Protego.parse(robots_bytes.decode('utf-8', 'strict'))
    redirect.policy = policy
    delay = max(delay, policy.crawl_delay(AGENT) or policy.crawl_delay('*') or 0)
    rate = policy.request_rate(AGENT) or policy.request_rate('*')
    if rate and rate.requests > 0:
        delay = max(delay, rate.seconds / rate.requests)
    queue = deque(filter(None, (normal_url(s) for s in policy.sitemaps)))
    if not queue:
        raise ValueError('No usable sitemap declared in robots.txt')
    visited, records, failures, skipped = set(), {}, [], Counter()
    output.mkdir(parents=True, exist_ok=True)
    observed_at = datetime.now(UTC).isoformat()
    while queue and len(visited) < max_sitemaps:
        sitemap = queue.popleft()
        if sitemap in visited:
            continue
        visited.add(sitemap)
        if not policy.can_fetch(sitemap, AGENT):
            skipped['sitemap_robots_disallowed'] += 1
            continue
        try:
            time.sleep(delay)
            body, _ = fetch(opener, sitemap)
            kind, rows = parse_sitemap(body)
            if kind == 'sitemapindex':
                for row in rows:
                    child = normal_url(row['url'])
                    if child and urllib.parse.urlsplit(child).path.endswith('.xml'):
                        queue.append(child)
                    else:
                        skipped['invalid_sitemap_url'] += 1
            else:
                for row in rows:
                    raw = row['url']
                    if normal_url(raw) is None:
                        skipped['external_or_invalid_url'] += 1
                        continue
                    item = records.setdefault(raw, {'url': raw, 'kind_hint': url_kind(raw),
                                                    'lastmod': row['lastmod'], 'sitemaps': [],
                                                    'robots_allowed': policy.can_fetch(raw, AGENT)})
                    if sitemap not in item['sitemaps']:
                        item['sitemaps'].append(sitemap)
        except (urllib.error.URLError, OSError, ValueError, ElementTree.ParseError) as error:
            failures.append({'sitemap': sitemap, 'error': type(error).__name__, 'detail': str(error)[:300]})
            break
        print(f'Processed sitemaps: {len(visited)}; unique URLs: {len(records)}', flush=True)
        # Snapshot after each map: an interruption preserves results but not a resumable queue.
        (output / 'urls.partial.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records.values()), encoding='utf-8')
    payload = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in records.values())
    (output / 'urls.jsonl').write_text(payload, encoding='utf-8')
    report = {'observed_at': observed_at, 'source': 'owner-published robots.txt sitemaps',
              'robots_sha256': hashlib.sha256(robots_bytes).hexdigest(),
              'sitemaps_processed_or_considered': len(visited), 'sitemaps_remaining': len(queue),
              'unique_urls': len(records), 'by_kind_hint': dict(Counter(r['kind_hint'] for r in records.values())),
              'robots_disallowed_urls': sum(not r['robots_allowed'] for r in records.values()),
              'errors': failures, 'skipped': dict(skipped), 'coverage_verified': False,
              'stopped_at_limit': bool(queue and len(visited) >= max_sitemaps),
              'limitations': 'URLs only: titles, prices, access, item availability and catalog completeness are unknown. No lessons or item pages fetched.'}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ca-file', type=Path, required=True)
    parser.add_argument('--delay', type=float, default=1.0)
    parser.add_argument('--max-sitemaps', type=int, default=50)
    args = parser.parse_args()
    report = discover(args.output, args.ca_file, args.delay, args.max_sitemaps)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report['errors'] or report['stopped_at_limit']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
