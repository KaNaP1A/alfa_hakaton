"""Build a reproducible blinded review pool from two fixed rankers."""
import argparse
import hashlib
import json
from pathlib import Path
from catboost import CatBoostRanker
from alfa_reco.bundle import atomic_json, sha256
from alfa_reco.search import SearchEngine


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog',type=Path,required=True)
    p.add_argument('--queries',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--top',type=int,default=4)
    a=p.parse_args()
    if a.output.exists(): raise ValueError('Output must be new')
    cases=json.loads(a.queries.read_text())['queries']
    if len({x['id'] for x in cases})!=len(cases) or len({x['family'] for x in cases})!=len(cases):
        raise ValueError('Repeated query id or family')
    engine=SearchEngine(a.catalog); backend=engine.relevance_backend(); baseline=backend.model
    candidate=CatBoostRanker(); candidate.load_model(str(a.candidate))
    metadata={row['entity_key']:row for row in engine.catalog}
    pools=[]; rankings=[]
    for case in cases:
        ranks={}
        for name,model in [('baseline',baseline),('persona',candidate)]:
            backend.model=model
            result=engine.search(case['query'],mode='relevance',top=a.top)
            ranks[name]=[r['entity_key'] for r in result['results']]
        ids=set(ranks['baseline'])|set(ranks['persona'])
        ids=sorted(ids,key=lambda key:hashlib.sha256((case['id']+'\0'+key).encode()).hexdigest())
        candidates=[]
        for key in ids:
            item=metadata[key]
            candidates.append({'entity_key':key,'kind':item['kind'],'title':item['title'],
                               'description':item.get('description',''), 'origin':item.get('experiment_origin','backup')})
        pools.append({**case,'candidates':candidates});rankings.append({'id':case['id'],'rankings':ranks})
        print('Built',case['id'],len(ids),flush=True)
    a.output.mkdir(parents=True)
    for name,rows in [('pool.jsonl',pools),('rankings.jsonl',rankings)]:
        (a.output/name).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows))
    atomic_json(a.output/'manifest.json',{'catalog_sha256':engine.manifest['catalog_sha256'],'queries_sha256':sha256(a.queries),'candidate_sha256':sha256(a.candidate),'pool_sha256':sha256(a.output/'pool.jsonl'),'top_per_ranker':a.top,'note':'Assistant-written queries; randomized candidates, human ratings absent.'})

if __name__=='__main__':main()
