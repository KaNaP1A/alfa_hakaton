"""Choose reproducible, disjoint title families for weak-query training."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from generate_local_relevance_queries import eligible_sources
from prepare_persona_corpus import normalize
from alfa_reco.bundle import atomic_json, sha256


def select(corpus, cases_path, limit):
    catalog = json.loads((corpus / 'catalog.json').read_text())
    cases = json.loads(cases_path.read_text())['queries']
    eligible = {r['entity_key'] for r in eligible_sources(catalog, cases, 42)}
    buckets = {'external': [], 'internal': []}
    for line in (corpus / 'persona_queries.jsonl').read_text().splitlines():
        row = json.loads(line)
        if row['split'] == 'train' and row['target'] in eligible:
            buckets['external' if row['origin'] == 'huggingface_training_only' else 'internal'].append(row)
    for rows in buckets.values():
        rows.sort(key=lambda r: hashlib.sha256(('sample42:' + r['id']).encode()).hexdigest())
    result, families = [], set()
    while len(result) < limit and any(buckets.values()):
        for rows in buckets.values():
            while rows:
                row = rows.pop()
                if row['family'] not in families:
                    families.add(row['family'])
                    result.append(row)
                    break
            if len(result) == limit:
                break
    if len(result) < limit:
        raise ValueError(f'Only {len(result)} eligible families available')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--corpus', type=Path, required=True)
    p.add_argument('--cases', type=Path, default=Path('evaluation/ensemble_cases_v2.json'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--heldout-output', type=Path,
                   help='Write IDs of validation/test title families to exclude from negative sampling')
    p.add_argument('--limit', type=int, default=700)
    a = p.parse_args()
    rows = select(a.corpus, a.cases, a.limit)
    if a.heldout_output:
        query_rows = [json.loads(line) for line in (a.corpus / 'persona_queries.jsonl').read_text().splitlines()]
        families = {row['family'] for row in query_rows if row['split'] in {'validation', 'test'}}
        catalog = json.loads((a.corpus / 'catalog.json').read_text())
        excluded = sorted(row['entity_key'] for row in catalog if normalize(row['title']) in families)
        if set(excluded) & {row['target'] for row in rows}:
            raise ValueError('Held-out title family overlaps training targets')
        if a.heldout_output.exists():
            raise ValueError('Held-out output must not exist')
        atomic_json(a.heldout_output, excluded)
    with a.output.open('x', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    atomic_json(a.output.with_suffix('.manifest.json'), {'query_count': len(rows), 'origins': dict(Counter(r['origin'] for r in rows)), 'styles': dict(Counter(str(r['style_id']) for r in rows)), 'sha256': sha256(a.output), 'cases_sha256': sha256(a.cases), 'notice': 'Weak templated source preferences, not human relevance labels.'})
    print(json.dumps(dict(Counter(r['origin'] for r in rows)), ensure_ascii=False))


if __name__ == '__main__': main()
