"""Build a versioned unified search bundle without modifying the source model."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from alfa_reco.bundle import atomic_json, load_bundle, sha256
from alfa_reco.eligibility import USER_KINDS
from alfa_reco.relevance import FEATURES, build_index, code_hashes
from alfa_reco.search import SearchEngine
from alfa_reco.suggestions import build_index as build_suggestions
from build_offline_mixed_index import merge_snapshot
from prepare_persona_corpus import inferred_tags

TAG_MAP = {
    'Финансы и налоги': 'Финансы', 'Маркетинг и продажи': 'Маркетинг',
    'Команда и управление': 'Управление командой', 'Технологии и данные': 'Технологии',
    'Запуск и развитие бизнеса': 'Развитие бизнеса', 'Право и договоры': 'Налоги и законы',
}


def build(baseline, source, encoder, output):
    baseline_path, base_meta, original = load_bundle(baseline)
    source_data = json.loads(source.read_text(encoding='utf-8'))
    cards = source_data['items']
    if len({x['id'] for x in cards}) != len(cards):
        raise ValueError('Duplicate source cards')
    baseline_keys = {x['entity_key'] for x in original}
    filtered = []
    for card in cards:
        candidate = card.get('historical_title_candidate')
        if card['origin'] == 'public_snapshot' and candidate:
            if candidate not in baseline_keys or not candidate.startswith(card['kind'] + ':'):
                raise ValueError('Title candidate is not in the baseline catalog')
            continue
        filtered.append(card)
    merged, counts = merge_snapshot(original, filtered)
    merged = [dict(item) for item in merged]
    by_key = {x['entity_key']: x for x in merged}
    for card in cards:
        kind, origin = card['kind'], card['origin']
        if kind == 'lesson' and origin == 'synthetic':
            token = hashlib.sha256((origin + '\0' + card['id']).encode()).hexdigest()[:24]
            key = 'lesson:unified-' + token
            if key in by_key:
                raise ValueError('Duplicate lesson key')
            item = {'entity_key': key, 'source_id': 'unified-' + token, 'kind': kind,
                    'title': card['title'], 'description': card['description'], 'body': '',
                    'topics': card.get('topics', []), 'tags': [], 'industries': [], 'lessons': [],
                    'search_text': card['title'] + ' ' + card['description'], 'access_type': 'unknown',
                    'canonical_url': None, 'source_url': None, 'price_raw': None, 'price_currency': None,
                    'publication_status': 'unknown', 'experiment_origin': 'synthetic',
                    'data_quality_flags': ['synthetic', 'unverified_platform_identity']}
            merged.append(item)
            by_key[key] = item
        elif origin == 'historical_backup':
            key = card['historical_entity_key']
        elif card.get('historical_title_candidate'):
            key = card['historical_title_candidate']
        else:
            exact = f"{kind}:{card['source_id']}" if card.get('source_id') else None
            if origin == 'public_snapshot' and exact in baseline_keys:
                key = exact
            else:
                token = hashlib.sha256((origin + '\0' + card['id']).encode()).hexdigest()[:24]
                key = kind + ':offline-' + token
        if key not in by_key:
            raise ValueError(f'Missing merged key: {key}')
        target = by_key[key]
        if target.get('supplement_display'):
            raise ValueError(f'Multiple display cards map to one key: {key}')
        target['supplement_display'] = {'origin': origin, 'title': card['title'],
            'description': card.get('description', ''), 'topics': card.get('topics', []),
            'source_url': card.get('source_url'),
            'identity': 'title_candidate_unverified' if card.get('historical_title_candidate') else
                        'synthetic' if origin == 'synthetic' else 'source_id' if card.get('source_id') else 'snapshot_only'}
        evidence = inferred_tags(card['title'], card.get('description', ''))
        inferred = list(dict.fromkeys(TAG_MAP[row['tag']] for row in evidence))
        if inferred and not target.get('topics') and not target.get('tags'):
            target['tags'] = inferred
            target['taxonomy_evidence'] = evidence
            target['data_quality_flags'] = list(dict.fromkeys(
                target.get('data_quality_flags', []) + ['inferred_topics_unverified']))
        if not target['supplement_display']['topics']:
            target['supplement_display']['topics'] = inferred
        if card.get('demo_offer'):
            target['conditional_offer'] = card['demo_offer']
    if len(by_key) != len(merged):
        raise ValueError('Duplicate material ID')
    old_root = baseline_path / 'relevance'
    old = old_root / json.loads((old_root / 'CURRENT.json').read_text())['generation']
    old_meta = json.loads((old / 'manifest.json').read_text())
    if old_meta['catalog_sha256'] != base_meta['catalog_sha256'] or old_meta['features'] != FEATURES or old_meta['source_hashes'] != code_hashes():
        raise ValueError('Baseline model is incompatible')
    if sha256(old / 'ranker.cbm') != old_meta['ranker_sha256']:
        raise ValueError('Baseline ranker checksum mismatch')
    output.mkdir(parents=True, exist_ok=False)
    stage = output / 'staging'
    stage.mkdir()
    atomic_json(stage / 'catalog.json', merged)
    digest = sha256(stage / 'catalog.json')
    generation = 'generation-unified-' + digest[:16]
    path = output / generation
    stage.rename(path)
    atomic_json(path / 'suggestions.json', build_suggestions(merged, digest))
    atomic_json(path / 'manifest.json', {'schema_version': 1, 'catalog_sha256': digest,
        'suggestions': {'sha256': sha256(path / 'suggestions.json')}, 'semantic': None,
        'catalog_count': len(merged), 'source_generation': baseline_path.name,
        'profile_compatible_generations': [baseline_path.name], 'source_catalog_sha256': base_meta['catalog_sha256'],
        'source_listing_sha256': sha256(source), 'merge_counts': counts,
        'notice': 'Public/backup listings and fictional values are unverified; actual access remains separately checked.'})
    atomic_json(output / 'CURRENT.json', {'generation': generation})
    engine = SearchEngine(output)
    relevance = path / 'relevance' / 'model-unified'
    meta = build_index(engine, encoder, relevance)
    if meta['encoder_fingerprint'] != old_meta['encoder_fingerprint']:
        raise ValueError('Encoder differs from baseline')
    shutil.copy2(old / 'ranker.cbm', relevance / 'ranker.cbm')
    meta.update({'ranker_sha256': sha256(relevance / 'ranker.cbm'), 'policy': old_meta['policy'],
                 'canonical': old_meta.get('canonical', True), 'ranking_parameters': old_meta['ranking_parameters'],
                 'ranker_provenance': 'baseline ranker, rebuilt index, no synthetic purchase claims'})
    atomic_json(relevance / 'manifest.json', meta)
    atomic_json(path / 'relevance' / 'CURRENT.json', {'generation': relevance.name})
    SearchEngine(output).relevance_backend()
    print(json.dumps({'generation': generation, 'items': len(merged), 'merge_counts': counts,
                      'catalog_sha256': digest, 'conditional_offers': sum('conditional_offer' in x for x in merged)}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=Path('../models/runtime/catalog'))
    parser.add_argument('--source', type=Path, default=Path('../data/demo_catalog.json'))
    parser.add_argument('--encoder', type=Path, default=Path('../models/recommender/encoder'))
    parser.add_argument('--output', type=Path, default=Path('../models/unified/catalog'))
    args = parser.parse_args()
    build(args.baseline, args.source, args.encoder, args.output)


if __name__ == '__main__':
    main()
