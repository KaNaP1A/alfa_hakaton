"""Compare fixed baseline ranker on old vs expanded offline index; no tuning or installation."""
import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

from audit_ranking import family_average, pooled_metrics, validate_cases

from alfa_reco.bundle import atomic_json, sha256
from alfa_reco.search import SearchEngine


def slices_by_kind(result, catalog):
    kinds = {item['entity_key']: item['kind'] for item in catalog}
    groups = {}
    for row in result['rows']:
        for kind in {kinds[key] for key in row['positive_ids']}:
            groups.setdefault((row['split'], kind), []).append(row)
    return {split + ':' + kind: family_average(rows)
            for (split, kind), rows in sorted(groups.items())}


def evaluate(engine, cases):
    backend = engine.relevance_backend()
    original = backend.result
    capture = {}
    def capture_result(*args, **kwargs):
        value = original(*args, **kwargs)
        capture['candidates'] = {engine.catalog[i]['entity_key'] for i in value['candidates']}
        return value
    backend.result = capture_result
    rows = []
    for index, case in enumerate(cases, 1):
        capture.clear()
        result = engine.search(case['query'], mode='relevance', top=5)
        ranked = [item['entity_key'] for item in result['results']]
        labels = {j['entity_key']: j['grade'] for j in case['judgments']}
        relevant = {key for key, grade in labels.items() if grade >= 2}
        candidates = capture.get('candidates', set())
        rows.append({
            'id': case['id'], 'family': case['family'], 'split': case['split'],
            'metrics': pooled_metrics(ranked, labels),
            'positive_ids': sorted(relevant),
            'candidate_recall': len(relevant & candidates) / len(relevant) if relevant else None,
            'shown_recall': len(relevant & set(ranked)) / len(relevant) if relevant else None,
            'diagnostics': result['retrieval_diagnostics'],
            'result_ids': ranked,
        })
        if index % 25 == 0:
            print(f'{engine.generation}: {index}/{len(cases)}', flush=True)
    summary = {}
    for split in sorted({r['split'] for r in rows}):
        subset = [r for r in rows if r['split'] == split]
        metrics = family_average(subset)
        for field in ['candidate_recall', 'shown_recall']:
            values = [r[field] for r in subset if r[field] is not None]
            metrics[field + '_query_mean'] = statistics.mean(values) if values else None
        for field in ['retrieved_candidates', 'considered_candidates', 'rejected_candidates']:
            metrics['mean_' + field] = statistics.mean(r['diagnostics'][field] for r in subset)
        summary[split] = metrics
    return {'generation': engine.generation, 'catalog_sha256': engine.manifest['catalog_sha256'],
            'summary': summary, 'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=Path('../models/runtime/catalog'))
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--cases', type=Path, default=Path('evaluation/ensemble_cases_v2.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output must not exist')
    cases = json.loads(args.cases.read_text())['queries']
    baseline, candidate = SearchEngine(args.baseline), SearchEngine(args.candidate)
    validate_cases(cases, baseline.catalog)
    validate_cases(cases, candidate.catalog)
    older = evaluate(baseline, cases)
    newer = evaluate(candidate, cases)
    old_rows = {r['id']: r for r in older['rows']}
    changes = Counter()
    for row in newer['rows']:
        prev = old_rows[row['id']]
        changes['same_top5_order'] += row['result_ids'] == prev['result_ids']
        changes['both_empty'] += not row['result_ids'] and not prev['result_ids']
        changes['became_empty'] += not row['result_ids'] and bool(prev['result_ids'])
        changes['became_nonempty'] += bool(row['result_ids']) and not prev['result_ids']
    report = {
        'cases_sha256': sha256(args.cases), 'case_count': len(cases),
        'baseline': older, 'candidate': newer, 'changes': dict(changes),
        'by_kind': {'baseline': slices_by_kind(older, baseline.catalog),
                    'candidate': slices_by_kind(newer, candidate.catalog)},
        'limitations': 'Assistant-labeled synthetic queries, only 4 judgments/query; test previously observed. Unjudged counted as zero in pooled metrics, so new materials have no labels; not a reliable quality or sales estimate.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, report)
    print(json.dumps({'baseline': older['summary'], 'candidate': newer['summary'], 'changes': dict(changes)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
