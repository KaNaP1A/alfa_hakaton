"""Build an isolated experimental index; never updates the running catalog or model."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

from alfa_reco.bundle import atomic_json, load_bundle, sha256
from alfa_reco.eligibility import USER_KINDS
from alfa_reco.relevance import FEATURES, build_index, code_hashes
from alfa_reco.search import SearchEngine
from alfa_reco.suggestions import build_index as build_suggestions


def merge_snapshot(baseline, demo):
    """Keep old IDs unchanged; identify additions without asserting platform identity."""
    if not isinstance(baseline, list) or not isinstance(demo, list):
        raise ValueError("Expected two catalog lists")
    keys = [item['entity_key'] for item in baseline]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate baseline IDs')
    baseline_keys = set(keys)
    candidates, seen_ids, stats = [], set(), Counter()
    for item in demo:
        kind, origin, identity = item.get('kind'), item.get('origin'), item.get('id')
        if not isinstance(identity, str) or not identity or identity in seen_ids:
            raise ValueError('Missing or duplicate demo record ID')
        seen_ids.add(identity)
        if origin == 'historical_backup':
            key = item.get('historical_entity_key')
            if (kind not in USER_KINDS or not isinstance(key, str) or key not in baseline_keys
                    or not key.startswith(kind + ':')):
                raise ValueError('Historical demo record does not match baseline')
            stats['retained_historical_exact_id'] += 1
            continue
        if kind == 'lesson' and origin == 'synthetic':
            # Lessons are demo-only: the running search schema indexes them inside courses.
            stats['excluded_synthetic_lesson_unsupported'] += 1
            continue
        if kind not in USER_KINDS or origin not in {'public_snapshot', 'synthetic'}:
            raise ValueError('Invalid demo record kind or origin')
        title, description = item.get('title'), item.get('description')
        if not isinstance(title, str) or not title.strip() or not isinstance(description, str):
            raise ValueError('Invalid demo title or description')
        source_id = item.get('source_id')
        exact = f'{kind}:{source_id}' if isinstance(source_id, str) and source_id else None
        if origin == 'public_snapshot' and exact in baseline_keys:
            stats['retained_baseline_exact_id'] += 1
            continue
        # Every added key is namespaced and never claims a verified platform ID.
        token = hashlib.sha256((origin + '\0' + identity).encode()).hexdigest()[:24]
        key = f'{kind}:offline-{token}'
        if key in baseline_keys:
            raise ValueError('Candidate ID collides with baseline')
        baseline_keys.add(key)
        topics = item.get('topics', []) if origin == 'synthetic' else []
        if not isinstance(topics, list) or any(not isinstance(t, str) for t in topics):
            raise ValueError('Invalid synthetic topic')
        candidates.append({
            'entity_key': key, 'source_id': 'offline-' + token, 'kind': kind,
            'title': title.strip(), 'description': description, 'body': '',
            'topics': topics, 'tags': [], 'industries': [], 'lessons': [],
            'search_text': title + ' ' + description, 'access_type': 'unknown',
            'canonical_url': None, 'source_url': None, 'price_raw': None,
            'price_currency': None, 'publication_status': 'unknown',
            'data_quality_flags': ['offline_experiment', 'unverified_platform_identity'],
            'experiment_origin': origin,
        })
        stats['added_' + origin] += 1
    return list(baseline) + sorted(candidates, key=lambda x: x['entity_key']), dict(stats)


def build(baseline_root, demo_path, encoder_path, output):
    baseline_path, baseline_manifest, baseline = load_bundle(baseline_root)
    demo = json.loads(Path(demo_path).read_text(encoding='utf-8'))
    merged, stats = merge_snapshot(baseline, demo['items'])
    old_relevance = baseline_path / 'relevance'
    old_model = old_relevance / json.loads((old_relevance / 'CURRENT.json').read_text())['generation']
    old_meta = json.loads((old_model / 'manifest.json').read_text())
    if old_meta['catalog_sha256'] != baseline_manifest['catalog_sha256']:
        raise ValueError('Baseline model and catalog mismatch')
    if old_meta['features'] != FEATURES or old_meta['source_hashes'] != code_hashes():
        raise ValueError('Baseline ranker features or source code differ')
    if sha256(old_model / 'ranker.cbm') != old_meta['ranker_sha256']:
        raise ValueError('Baseline ranker checksum mismatch')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    staging = output / 'staging'
    staging.mkdir()
    atomic_json(staging / 'catalog.json', merged)
    digest = sha256(staging / 'catalog.json')
    generation = 'generation-offline-' + digest[:16]
    path = output / generation
    staging.rename(path)
    atomic_json(path / 'suggestions.json', build_suggestions(merged, digest))
    atomic_json(path / 'manifest.json', {
        'schema_version': 1, 'catalog_sha256': digest,
        'suggestions': {'sha256': sha256(path / 'suggestions.json')},
        'semantic': None, 'experimental': True, 'catalog_count': len(merged),
        'source_generation': baseline_path.name, 'source_catalog_sha256': baseline_manifest['catalog_sha256'],
        'demo_sha256': sha256(demo_path), 'merge_counts': stats,
        'notice': 'Offline experiment. Added identities, publication, offers and access are not verified.',
    })
    atomic_json(output / 'CURRENT.json', {'generation': generation})
    engine = SearchEngine(output)
    # BM25's field indexes are built in memory from this versioned catalog by SearchEngine.
    relevance = path / 'relevance' / 'model-offline'
    meta = build_index(engine, encoder_path, relevance)
    if meta['encoder_fingerprint'] != old_meta['encoder_fingerprint']:
        raise ValueError('Encoder is not compatible with the baseline ranker')
    shutil.copy2(old_model / 'ranker.cbm', relevance / 'ranker.cbm')
    meta.update({
        'ranker_sha256': sha256(relevance / 'ranker.cbm'),
        'policy': old_meta['policy'], 'canonical': old_meta.get('canonical', True),
        'ranking_parameters': old_meta['ranking_parameters'],
        'ranker_provenance': 'unchanged baseline ranker, applied experimentally to expanded catalog',
        'baseline_model_manifest_sha256': sha256(old_model / 'manifest.json'),
        'experimental': True,
    })
    atomic_json(relevance / 'manifest.json', meta)
    atomic_json(path / 'relevance' / 'CURRENT.json', {'generation': relevance.name})
    # Fail closed if ordering, dimensions, hashes, encoder or feature schema are incompatible.
    SearchEngine(output).relevance_backend()
    return {'generation': generation, 'catalog_count': len(merged), 'merge_counts': stats,
            'catalog_sha256': digest, 'ranker_sha256': meta['ranker_sha256'],
            'encoder_fingerprint': meta['encoder_fingerprint'], 'output': str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=Path('../models/runtime/catalog'))
    parser.add_argument('--demo', type=Path, default=Path('../data/demo_catalog.json'))
    parser.add_argument('--encoder', type=Path, default=Path('../models/recommender/encoder'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.baseline, args.demo, args.encoder, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
