"""Train simulated engagement/purchase models using the existing catalog and E5 vectors.

The source catalog is an offline snapshot and does not prove current offers or rights.
Every user action, offer type, amount and label is synthetic.
"""
import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import catboost
import numpy as np
from catboost import CatBoostClassifier
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from alfa_reco.bundle import load_bundle, sha256

KINDS = ('article', 'calculator', 'course', 'document', 'lesson', 'podcast', 'webinar')
FEATURES = ('cosine', 'base_rank_percentile', *(f'kind_{k}' for k in KINDS),
            'offer_paid', 'offer_subscription', 'log_price', 'budget_known', 'log_budget', 'price_to_budget')


def split_catalog(catalog):
    """Separate identical normalized titles by kind across splits; stratify kinds."""
    groups = defaultdict(lambda: defaultdict(list))
    for i, item in enumerate(catalog):
        kind, title = item.get('kind'), item.get('title', '')
        if kind in KINDS and isinstance(title, str) and title.strip():
            groups[kind][' '.join(title.casefold().split())].append(i)
    splits = {'train': [], 'validation': [], 'test': []}
    for kind, title_groups in groups.items():
        keys = sorted(title_groups, key=lambda title: hashlib.sha256((kind + ':' + title).encode()).hexdigest())
        n = len(keys)
        n_test = max(1, round(n * 0.2)) if n >= 3 else 0
        n_val = max(1, round(n * 0.1)) if n - n_test >= 2 else 0
        for index, title in enumerate(keys):
            target = 'test' if index < n_test else 'validation' if index < n_test + n_val else 'train'
            splits[target].extend(title_groups[title])
    return splits


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -20, 20)))


def sample_sessions(catalog, vectors, indexes, count, seed, stress=False, price_pool=None):
    rng = np.random.default_rng(seed)
    if len(indexes) < 12:
        raise ValueError('Need at least 12 materials in each split')
    indexes = np.asarray(indexes, dtype=np.int32)
    sub = vectors[indexes]
    cosine_matrix = np.clip(sub @ sub.T, -1, 1)
    np.fill_diagonal(cosine_matrix, -2)
    # Each material serves as an anchor at least once if count >= number of materials.
    anchors = np.resize(rng.permutation(len(indexes)), count)
    sessions = []
    for session_id, anchor in enumerate(anchors):
        cosines = cosine_matrix[anchor]
        nearest = np.argpartition(cosines, -5)[-5:]
        eligible_random = np.setdiff1d(np.arange(len(indexes)), np.append(nearest, anchor), assume_unique=False)
        random_candidates = rng.choice(eligible_random, 5, replace=False)
        candidates = np.concatenate((nearest, random_candidates))
        candidates = candidates[np.argsort(-cosines[candidates])]
        budget = int(rng.choice([2500, 5000, 10000, 20000, 50000, 100000]))
        disclosed = budget if rng.random() < 0.5 else 0
        sensitivity = float(rng.uniform(1.5, 2.5) if stress else rng.uniform(0.7, 1.5))
        positions = rng.permutation(len(candidates))
        events = []
        for rank, (candidate, position) in enumerate(zip(candidates, positions, strict=True)):
            source_index = int(indexes[candidate])
            source = catalog[source_index]
            # Counterfactual offer state/price are assigned at random, regardless of actual access.
            offer_state = str(rng.choice(['free', 'paid', 'subscription'], p=[0.45, 0.4, 0.15]))
            prices = price_pool if price_pool is not None else [990, 1990, 3990, 9990, 14990, 29990, 54900]
            price = 0 if offer_state == 'free' else int(rng.choice(prices))
            sim = float(cosines[candidate])
            price_ratio = price / budget
            engagement_p = float(sigmoid(-0.9 + 4.5 * (sim - 0.65) - sensitivity * max(0, price_ratio - 0.4)))
            # The small free-content path is a fictional later purchase, not an observed transaction.
            paid_probability = float(sigmoid(-1.5 + 2.2 * (sim - 0.65) - sensitivity * max(0, price_ratio - 0.5)))
            purchase_p = engagement_p * (0.16 if offer_state == 'free' else paid_probability)
            seen = bool(rng.random() < 0.9 / math.sqrt(int(position) + 1))
            engaged = bool(rng.random() < engagement_p) if seen else None
            purchased = bool(engaged and rng.random() < purchase_p / engagement_p) if seen else None
            kind_onehot = [float(source['kind'] == kind) for kind in KINDS]
            features = [sim, rank / (len(candidates) - 1), *kind_onehot,
                        float(offer_state == 'paid'), float(offer_state == 'subscription'),
                        math.log1p(price), float(disclosed > 0), math.log1p(disclosed),
                        min(price / disclosed, 10) if disclosed else 0]
            events.append({'synthetic': True, 'session_id': session_id,
                           'anchor_key': catalog[int(indexes[anchor])]['entity_key'],
                           'entity_key': source['entity_key'], 'kind': source['kind'],
                           'snapshot_access': source.get('access_type'),
                           'synthetic_offer_state': offer_state, 'synthetic_price_rub': price,
                           'base_rank': rank, 'randomized_position': int(position),
                           'examined': seen, 'engaged': engaged, 'purchased': purchased,
                           'features': features})
        sessions.extend(events)
    return sessions


def arrays(rows, label):
    examined = [r for r in rows if r['examined']]
    return (np.asarray([r['features'] for r in examined], dtype=np.float32),
            np.asarray([int(r[label]) for r in examined], dtype=np.int32))


def evaluate(model, rows, label, baseline_rate):
    x, y = arrays(rows, label)
    prob = model.predict_proba(x)[:, 1]
    return {'examined_rows': len(y), 'positive_rate_synthetic': round(float(y.mean()), 4),
            'roc_auc_synthetic': round(float(roc_auc_score(y, prob)), 4),
            'logloss_synthetic': round(float(log_loss(y, prob)), 4),
            'brier_synthetic': round(float(brier_score_loss(y, prob)), 4),
            'constant_baseline_logloss': round(float(log_loss(y, np.full(len(y), baseline_rate))), 4),
            'constant_baseline_brier': round(float(brier_score_loss(y, np.full(len(y), baseline_rate))), 4),
            'by_kind': {k: {'examined': sum(r['examined'] and r['kind'] == k for r in rows),
                            'positives': sum(r['examined'] and r['kind'] == k and r[label] for r in rows)}
                        for k in KINDS}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=Path('artifacts/catalog'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/mixed_catalog_simulation_v1'))
    parser.add_argument('--train-sessions', type=int, default=5000)
    parser.add_argument('--test-sessions', type=int, default=1500)
    parser.add_argument('--observed-prices', type=Path,
                        help='Historical observations supply extra simulated price points, never verified offers')
    parser.add_argument('--exclude-origin', action='append', default=[],
                        help='Exclude an experiment_origin from simulation (may be repeated)')
    parser.add_argument('--allowed-keys', type=Path,
                        help='JSON list of independently checked material keys to include')
    args = parser.parse_args()
    if args.train_sessions < 50 or args.test_sessions < 50:
        parser.error('Require at least 50 sessions')
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output must be new or empty')
    catalog_path, manifest, catalog = load_bundle(args.catalog)
    relevance_root = catalog_path / 'relevance'
    generation = json.loads((relevance_root / 'CURRENT.json').read_text())['generation']
    if not isinstance(generation, str) or Path(generation).name != generation or generation.startswith('.'):
        raise ValueError('Invalid relevance generation')
    relevance_path = relevance_root / generation
    rel_manifest = json.loads((relevance_path / 'manifest.json').read_text())
    if rel_manifest['catalog_sha256'] != manifest['catalog_sha256']:
        raise ValueError('E5 vectors do not match catalog')
    if sha256(relevance_path / 'vectors.npz') != rel_manifest['index_sha256']:
        raise ValueError('E5 vectors hash mismatch')
    normalized_path = relevance_path / 'normalized_catalog.json'
    if sha256(normalized_path) != rel_manifest['normalized_catalog_sha256']:
        raise ValueError('Normalized catalog hash mismatch')
    normalized = json.loads(normalized_path.read_text())
    if [i['entity_key'] for i in normalized] != [i['entity_key'] for i in catalog]:
        raise ValueError('E5 vectors and catalog order differ')
    with np.load(relevance_path / 'vectors.npz', allow_pickle=False) as archive:
        vectors = archive['card'].copy()
    if vectors.shape != (len(catalog), 384) or not np.isfinite(vectors).all():
        raise ValueError('Invalid vectors')
    prices = [990, 1990, 3990, 9990, 14990, 29990, 54900]
    if args.observed_prices:
        observations = json.loads(args.observed_prices.read_text())
        for observation in observations:
            amount = observation['observed_price_rub']
            if isinstance(amount, bool) or not isinstance(amount, int) or not 0 < amount <= 10000000:
                raise ValueError('Invalid historical price observation')
            prices.append(amount)
    prices = sorted(set(prices))
    permitted = None
    if args.allowed_keys:
        values = json.loads(args.allowed_keys.read_text())
        if not isinstance(values, list) or any(not isinstance(key, str) for key in values):
            raise ValueError('Allowed material keys must be a JSON string list')
        permitted = set(values)
        if len(permitted) != len(values) or not permitted <= {item['entity_key'] for item in catalog}:
            raise ValueError('Allowed material keys must be unique and present in the catalog')
    splits = split_catalog(catalog)
    splits = {name: [i for i in indices if catalog[i].get('experiment_origin') not in args.exclude_origin]
              for name, indices in splits.items()}
    if permitted is not None:
        splits = {name: [i for i in indices if catalog[i]['entity_key'] in permitted]
                  for name, indices in splits.items()}
    train = sample_sessions(catalog, vectors, splits['train'], args.train_sessions, 31001, price_pool=prices)
    val = sample_sessions(catalog, vectors, splits['validation'], max(300, args.train_sessions // 5), 31002, price_pool=prices)
    test = sample_sessions(catalog, vectors, splits['test'], args.test_sessions, 31003, price_pool=prices)
    stress = sample_sessions(catalog, vectors, splits['test'], args.test_sessions, 31004, stress=True, price_pool=prices)
    args.output.mkdir(parents=True, exist_ok=True)
    reports = {}
    for label in ('engaged', 'purchased'):
        x, y = arrays(train, label)
        vx, vy = arrays(val, label)
        model = CatBoostClassifier(iterations=450, depth=5, learning_rate=0.04, l2_leaf_reg=8,
                                   loss_function='Logloss', random_seed=42, thread_count=2,
                                   verbose=False, allow_writing_files=False)
        model.fit(x, y, eval_set=(vx, vy), early_stopping_rounds=40)
        model.save_model(str(args.output / f'synthetic_{label}.cbm'))
        reports[label] = {'trees': model.tree_count_, 'train_positive_rate': round(float(y.mean()), 4),
                          'base': evaluate(model, test, label, float(y.mean())),
                          'stress': evaluate(model, stress, label, float(y.mean()))}
    with (args.output / 'synthetic_train.jsonl').open('w', encoding='utf-8') as f:
        for row in train:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    included = {i for indices in splits.values() for i in indices}
    origins = Counter(catalog[i].get('experiment_origin', 'historical_backup') for i in included)
    report = {'synthetic_only': True, 'source': 'offline catalog snapshot; not a verified current offer catalog',
              'catalog_origins': dict(origins),
              'excluded_origins': args.exclude_origin,
              'allowed_keys_sha256': sha256(args.allowed_keys) if args.allowed_keys else None,
              'simulated_catalog_items': len(included),
              'simulated_price_pool_rub': prices,
              'observed_prices_sha256': sha256(args.observed_prices) if args.observed_prices else None,
              'catalog_generation': catalog_path.name, 'catalog_sha256': manifest['catalog_sha256'],
              'catalog_items': len(catalog), 'kinds': dict(Counter(i['kind'] for i in catalog)),
              'split_counts': {k: len(v) for k, v in splits.items()},
              'synthetic_sessions': {'train': args.train_sessions, 'validation': max(300, args.train_sessions // 5),
                                     'test': args.test_sessions, 'stress': args.test_sessions},
              'training_rows': len(train), 'observed_training_rows': sum(r['examined'] for r in train),
              'source_snapshot_access': dict(Counter(str(catalog[i].get('access_type')) for i in included)),
              'model_features': FEATURES, 'catboost_version': catboost.__version__, 'models': reports,
              'limits': 'All prices, offers, user actions and relevance targets are simulated. E5 cosine uses '
                        'two material vectors, not real queries; distinct title groups across splits, but '
                        'duplicates and topics may overlap. Test results do not prove real sales or retention.'}
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    paths = [Path(__file__), relevance_path / 'vectors.npz', args.output / 'synthetic_engaged.cbm',
             args.output / 'synthetic_purchased.cbm']
    manifest_out = {'synthetic_only': True, 'catalog_sha256': manifest['catalog_sha256'],
                    'relevance_generation': generation, 'features': FEATURES,
                    'catboost_version': catboost.__version__,
                    'sha256': {str(path): sha256(path) for path in paths}}
    (args.output / 'manifest.json').write_text(json.dumps(manifest_out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
