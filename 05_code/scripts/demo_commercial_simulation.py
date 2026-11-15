"""Show isolated synthetic-price reranking on real relevance-search results.

The fake price/eligibility flags below are ONLY for an offline local demo. They
must never be used as platform price, offer, entitlement or purchase evidence.
"""
import argparse
import json
from pathlib import Path

from catboost import CatBoostClassifier

from alfa_reco.commercial_experiment import rerank_synthetic_only
from alfa_reco.search import SearchEngine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query', default='как управлять командой')
    parser.add_argument('--catalog', default='artifacts/catalog')
    parser.add_argument('--model', default='artifacts/commercial_simulation_v4/synthetic_purchase_model.cbm')
    args = parser.parse_args()
    model = CatBoostClassifier()
    model.load_model(str(Path(args.model)))
    engine = SearchEngine(args.catalog, llm_enabled=False)
    response = engine.search(args.query, mode='relevance', kind='course', top=10)
    offers = []
    amounts = (1499000, 399000, 5490000, 300000, 999000)
    for i, item in enumerate(response['results']):
        offers.append({'entity_key': item['entity_key'], 'offer_id': f'SYNTHETIC-OFFER-{i}',
                       'kind': 'course', 'price_minor': amounts[i % len(amounts)],
                       'currency': 'RUB', 'verified': True, 'purchasable': True,
                       'owned': False, 'valid_until': '2100-01-01T00:00:00Z'})
    result = rerank_synthetic_only(offers, model)
    print(json.dumps({'warning': 'OFFLINE DEMO: prices, offer IDs and verification flags are invented; '
                                  'not suitable for display to users or purchases.',
                      'query': args.query, 'generation': response['generation'],
                      'input_count': len(offers), 'simulation': result}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
