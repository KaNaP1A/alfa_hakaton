"""Train and evaluate a price-aware model on entirely simulated purchase behaviour."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import catboost
import numpy as np
from catboost import CatBoostClassifier

from alfa_reco.commercial_experiment import FEATURES, features, rerank_synthetic_only

EXAM = (0.90, 0.64, 0.43)


def logistic(x):
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def make_sessions(courses, count, seed, scenario):
    """Disjoint seeded populations. Source items are real; prices and users are invented."""
    rng = np.random.default_rng(seed)
    sessions = []
    for session_index in range(count):
        topic = str(rng.choice(sorted({c['category'] for c in courses})))
        budget = int(rng.choice([2500, 5000, 10000, 20000, 50000, 100000])) * 100
        disclosed = budget if rng.random() < 0.5 else None
        sensitivity = float(rng.uniform(0.75, 1.5)) if scenario == 'base' else float(rng.uniform(1.6, 2.6))
        candidates = []
        for index, course in enumerate(courses):
            same = course['category'] == topic
            relevance = float(np.clip(rng.normal(0.83 if same else 0.46, 0.09), 0.2, 0.99))
            # Counterfactual price interventions break the source-course/price correlation.
            price = int(rng.choice([1500, 3000, 3990, 6000, 9990, 14990, 29990, 54900, 110000])) * 100
            ratio = price / budget
            utility = -1.2 + 4.8 * (relevance - 0.5) - sensitivity * max(0.0, ratio - 0.55)
            if scenario == 'stress':
                utility -= 0.22 * math.log1p(price / 10000)
            p = logistic(utility)
            candidates.append({
                'entity_key': f'course:synthetic-{index}', 'offer_id': f'offer-{index}',
                'kind': 'course', 'price_minor': price, 'currency': 'RUB',
                'verified': True, 'purchasable': True, 'owned': False,
                'valid_until': '2100-01-01T00:00:00+00:00',
                'latent_relevance': relevance, 'synthetic_purchase_p': p,
                'purchase_uniform': float(rng.random()), 'exposure_uniform': float(rng.random()),
            })
        candidates.sort(key=lambda item: -item['latent_relevance'])
        sessions.append({'session_id': f'{scenario}-{seed}-{session_index}', 'topic': topic,
                         'budget_minor': budget, 'disclosed_budget_minor': disclosed,
                         'candidates': candidates})
    return sessions


def training_rows(sessions, seed):
    rng = np.random.default_rng(seed)
    rows, labels, records = [], [], []
    for session in sessions:
        positions = rng.permutation(len(session['candidates']))
        for base_rank, (candidate, position) in enumerate(zip(session['candidates'], positions, strict=True)):
            exposed = bool(rng.random() < (0.9 / math.sqrt(1 + int(position))))
            bought = bool(rng.random() < candidate['synthetic_purchase_p']) if exposed else False
            row = features(base_rank, len(session['candidates']), candidate['price_minor'],
                           session['disclosed_budget_minor'])
            records.append({'session_id': session['session_id'], 'synthetic': True,
                            'entity_key': candidate['entity_key'], 'base_rank': base_rank,
                            'randomized_position': int(position), 'examined': exposed,
                            'purchase': bought if exposed else None, 'features': row})
            if exposed:
                rows.append(row)
                labels.append(int(bought))
    return np.asarray(rows, dtype=np.float32), np.asarray(labels, dtype=np.int32), records


def stripped(candidate):
    keys = ('entity_key', 'offer_id', 'kind', 'price_minor', 'currency', 'verified',
            'purchasable', 'owned', 'valid_until')
    return {key: candidate[key] for key in keys}


def evaluate(sessions, model):
    totals = {policy: {'revenue': 0, 'purchases': 0, 'relevance': 0, 'over_budget': 0,
                       'first_price': 0, 'moved': 0} for policy in ('relevance', 'price_high', 'synthetic_model')}
    for session in sessions:
        originals = session['candidates']
        offers = [stripped(item) for item in originals]
        by_id = {item['offer_id']: item for item in originals}
        experimental = rerank_synthetic_only(offers, model, budget_minor=session['disclosed_budget_minor'])['results']
        policies = {'relevance': offers, 'price_high': sorted(offers, key=lambda x: -x['price_minor']),
                    'synthetic_model': experimental}
        for name, ordered in policies.items():
            row = totals[name]
            row['first_price'] += ordered[0]['price_minor'] / 100
            row['relevance'] += by_id[ordered[0]['offer_id']]['latent_relevance']
            row['over_budget'] += ordered[0]['price_minor'] > session['budget_minor']
            row['moved'] += ordered[0]['offer_id'] != offers[0]['offer_id']
            for position, offer in enumerate(ordered[:len(EXAM)]):
                item = by_id[offer['offer_id']]
                if item['exposure_uniform'] < EXAM[position] and item['purchase_uniform'] < item['synthetic_purchase_p']:
                    row['purchases'] += 1
                    row['revenue'] += offer['price_minor'] / 100
                    break
    n = len(sessions)
    return {name: {'synthetic_revenue_per_session_rub': round(v['revenue'] / n, 2),
                   'synthetic_purchase_rate': round(v['purchases'] / n, 4),
                   'synthetic_average_check_rub': round(v['revenue'] / v['purchases'], 2) if v['purchases'] else None,
                   'top1_relevance_simulated': round(v['relevance'] / n, 4),
                   'top1_over_hidden_budget_rate': round(v['over_budget'] / n, 4),
                   'top1_price_rub': round(v['first_price'] / n, 2),
                   'top1_changed_rate': round(v['moved'] / n, 4)} for name, v in totals.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/commercial_simulation_v1'))
    parser.add_argument('--train-sessions', type=int, default=5000)
    parser.add_argument('--test-sessions', type=int, default=2000)
    args = parser.parse_args()
    if args.train_sessions < 50 or args.test_sessions < 50:
        parser.error('Use at least 50 sessions per split')
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output must be a new or empty directory; existing runs are not overwritten')
    courses = json.loads(Path('experiments/alfa_public_courses.json').read_text())['courses']
    train = make_sessions(courses, args.train_sessions, 12001, 'base')
    validation = make_sessions(courses, max(100, args.train_sessions // 5), 12002, 'base')
    holdout = make_sessions(courses, args.test_sessions, 12003, 'base')
    stress = make_sessions(courses, args.test_sessions, 12004, 'stress')
    x_train, y_train, records = training_rows(train, 12005)
    x_val, y_val, _ = training_rows(validation, 12006)
    model = CatBoostClassifier(iterations=500, depth=5, learning_rate=0.04, l2_leaf_reg=8,
                               loss_function='Logloss', random_seed=42, thread_count=2,
                               verbose=False, allow_writing_files=False)
    model.fit(x_train, y_train, eval_set=(x_val, y_val), early_stopping_rounds=40)
    args.output.mkdir(parents=True, exist_ok=True)
    model.save_model(str(args.output / 'synthetic_purchase_model.cbm'))
    with (args.output / 'synthetic_training_rows.jsonl').open('w', encoding='utf-8') as f:
        for row in records:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    report = {'synthetic_only': True, 'site_course_examples': len(courses),
              'sessions': {'train': len(train), 'validation': len(validation), 'test_base': len(holdout),
                           'test_stress': len(stress)},
              'training': {'rows_all': len(records), 'rows_examined': len(x_train),
                           'simulated_purchase_rate_examined': round(float(y_train.mean()), 4),
                           'features': FEATURES, 'trees': model.tree_count_,
                           'feature_importance': dict(zip(FEATURES, [round(float(v), 3) for v in model.feature_importances_], strict=True))},
              'test_base': evaluate(holdout, model), 'test_stress': evaluate(stress, model),
              'limitations': 'All user behaviour, prices, labels and relevance are simulated. '
                             'Test sessions are independent of training but generated from assumed equations; '
                             'stress has different assumptions. No evidence of actual conversion, calibration, '
                             'user relevance, site revenue or deployment readiness.'}
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    paths = [Path('experiments/alfa_public_courses.json'), Path('scripts/train_commercial_simulation.py'),
             Path('src/alfa_reco/commercial_experiment.py'), args.output / 'synthetic_purchase_model.cbm']
    manifest = {'synthetic_only': True, 'catboost_version': catboost.__version__,
                'feature_names': FEATURES, 'train_sessions': args.train_sessions,
                'test_sessions': args.test_sessions,
                'sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
