"""Audit public site metadata without promoting snapshot prices or rights to facts."""
import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote, urlsplit

from alfa_reco.bundle import load_bundle


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def audit(rows, catalog):
    counts = Counter()
    by_kind = defaultdict(Counter)
    identities = defaultdict(list)
    old_ids = {item['entity_key'] for item in catalog}
    old_slugs = defaultdict(set)
    for item in catalog:
        slug = item.get('source_url')
        if isinstance(slug, str) and slug:
            old_slugs[(item.get('kind'), unquote(slug).strip('/').casefold())].add(item['entity_key'])
    urls = set()
    duplicates = 0
    for row in rows:
        kind = row.get('kind') or 'unknown'
        stats = by_kind[kind]
        stats['records'] += 1
        stats['missing_id'] += not bool(row.get('source_id'))
        stats['missing_description'] += not bool((row.get('description') or '').strip())
        stats['missing_title'] += not bool((row.get('title') or '').strip())
        stats['noindex_true'] += row.get('source_noindex_raw') is True
        stats['missing_publication_date'] += not bool(row.get('source_published_raw'))
        stats['status_or_price_unknown'] += (row.get('access_type') == 'unknown' or row.get('price_status') == 'unknown')
        if key := row.get('entity_key'):
            identities[key].append(row)
            stats['id_found_in_old_snapshot'] += key in old_ids
        elif row.get('source_url'):
            slug = unquote(urlsplit(row['source_url']).path.rstrip('/').split('/')[-1]).casefold()
            candidates = old_slugs.get((kind, slug), set())
            stats['unverified_single_slug_candidate'] += len(candidates) == 1
            stats['ambiguous_slug_candidate'] += len(candidates) > 1
        url = row.get('source_url')
        if url:
            if url in urls:
                duplicates += 1
            urls.add(url)
        counts['records'] += 1
    repeated = {key: group for key, group in identities.items() if len(group) > 1}
    conflicting = sum(len({(r.get('title'), r.get('kind')) for r in group}) > 1 for group in repeated.values())
    return {'records': counts['records'], 'by_kind': {kind: dict(data) for kind, data in sorted(by_kind.items())},
            'repeated_entity_keys': len(repeated), 'conflicting_entity_keys': conflicting,
            'repeated_source_urls': duplicates, 'coverage_verified': False,
            'limitations': 'Exact IDs only, not fuzzy identity; counts depend on fetched pages. No confirmation of current rights, prices, inventory coverage or inferred missing entities.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--vocabulary', type=Path, required=True)
    parser.add_argument('--calculators', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, default=Path('artifacts/catalog'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with closing(sqlite3.connect(f'file:{args.checkpoint.resolve()}?mode=ro', uri=True)) as db:
        rows = [json.loads(item[0]) for item in db.execute('SELECT payload FROM items')]
    rows += load_jsonl(args.vocabulary)
    rows += load_jsonl(args.calculators)
    _, manifest, catalog = load_bundle(args.catalog)
    report = audit(rows, catalog)
    report['historical_catalog_sha256'] = manifest['catalog_sha256']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
