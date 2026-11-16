"""Index the isolated persona training catalog without changing the live bundle."""
import argparse
import json
import shutil
from pathlib import Path
from alfa_reco.bundle import atomic_json, load_bundle, sha256
from alfa_reco.relevance import FEATURES, build_index, code_hashes
from alfa_reco.search import SearchEngine
from alfa_reco.suggestions import build_index as build_suggestions


def build(corpus, baseline, encoder, output):
    baseline_path, baseline_manifest, _ = load_bundle(baseline)
    root = baseline_path / 'relevance'
    old = root / json.loads((root / 'CURRENT.json').read_text())['generation']
    old_meta = json.loads((old / 'manifest.json').read_text())
    if old_meta['catalog_sha256'] != baseline_manifest['catalog_sha256'] or old_meta['features'] != FEATURES or old_meta['source_hashes'] != code_hashes() or sha256(old / 'ranker.cbm') != old_meta['ranker_sha256']:
        raise ValueError('Baseline ranker incompatible or checksum mismatch')
    corpus_meta = json.loads((corpus / 'manifest.json').read_text())
    if sha256(corpus / 'catalog.json') != corpus_meta['catalog_sha256']:
        raise ValueError('Corpus checksum mismatch')
    items = json.loads((corpus / 'catalog.json').read_text())
    output.mkdir(parents=True, exist_ok=False)
    generation = 'generation-persona-' + corpus_meta['catalog_sha256'][:16]
    path = output / generation
    path.mkdir()
    shutil.copy2(corpus / 'catalog.json', path / 'catalog.json')
    digest = sha256(path / 'catalog.json')
    atomic_json(path / 'suggestions.json', build_suggestions(items, digest))
    atomic_json(path / 'manifest.json', {'schema_version': 1, 'catalog_sha256': digest, 'suggestions': {'sha256': sha256(path / 'suggestions.json')}, 'semantic': None, 'experimental': True, 'catalog_count': len(items), 'source_generation': baseline_path.name, 'notice': 'Offline training-only catalog; external courses are not Alfa offers.'})
    atomic_json(output / 'CURRENT.json', {'generation': generation})
    engine = SearchEngine(output)
    model = path / 'relevance' / 'model-persona'
    meta = build_index(engine, encoder, model)
    if meta['encoder_fingerprint'] != old_meta['encoder_fingerprint']:
        raise ValueError('Incompatible encoder')
    shutil.copy2(old / 'ranker.cbm', model / 'ranker.cbm')
    meta.update({'ranker_sha256': sha256(model / 'ranker.cbm'), 'policy': old_meta['policy'], 'canonical': old_meta.get('canonical', True), 'ranking_parameters': old_meta['ranking_parameters'], 'ranker_provenance': 'unchanged baseline for offline training comparison', 'experimental': True})
    atomic_json(model / 'manifest.json', meta)
    atomic_json(path / 'relevance' / 'CURRENT.json', {'generation': model.name})
    SearchEngine(output).relevance_backend()
    print(json.dumps({'generation': generation, 'items': len(items), 'model': str(model)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, default=Path('../models/runtime/catalog'))
    parser.add_argument('--encoder', type=Path, default=Path('../models/recommender/encoder'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.corpus, args.baseline, args.encoder, args.output)
