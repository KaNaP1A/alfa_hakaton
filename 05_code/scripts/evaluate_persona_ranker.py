"""Compare rankers on held-out synthetic title-family probes, without installing them."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from catboost import CatBoostRanker
from alfa_reco.bundle import atomic_json, sha256
from alfa_reco.search import SearchEngine


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog',type=Path,required=True)
    p.add_argument('--queries',type=Path,required=True)
    p.add_argument('--training-queries',type=Path,required=True)
    p.add_argument('--ranker',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--per-group',type=int,default=20)
    a=p.parse_args()
    train={json.loads(x)['family'] for x in a.training_queries.read_text().splitlines()}
    buckets=defaultdict(list)
    for line in a.queries.read_text().splitlines():
        row=json.loads(line)
        if row['split'] not in {'validation','test'}: continue
        if row['family'] in train: raise ValueError('Title family leakage')
        origin='external' if row['origin']=='huggingface_training_only' else 'internal'
        buckets[(row['split'],origin)].append(row)
    chosen=[]
    for key,rows in sorted(buckets.items()):
        rows.sort(key=lambda r:hashlib.sha256(('holdout42:'+r['id']).encode()).hexdigest())
        families=set()
        for row in rows:
            if row['family'] in families: continue
            families.add(row['family']);chosen.append(row)
            if len(families)>=a.per_group: break
    engine=SearchEngine(a.catalog);backend=engine.relevance_backend();baseline=backend.model
    candidate=CatBoostRanker();candidate.load_model(str(a.ranker))
    indices={row['entity_key']:i for i,row in enumerate(engine.catalog)}
    totals=defaultdict(Counter); results=[]
    for n,row in enumerate(chosen,1):
        target=indices[row['target']];prepared=backend.prepare(row['query'])
        group=row['split']+':' + ('external' if row['origin']=='huggingface_training_only' else 'internal')
        result={'id':row['id'],'group':group,'retrieved':target in prepared['candidates']}
        for name,model in [('baseline',baseline),('trained',candidate)]:
            backend.model=model; ranked,_=backend.score(prepared)
            rank=(ranked.index(target)+1) if target in ranked else None
            result[name+'_rank']=rank
            totals[group][name+'_hit1']+=rank==1
            totals[group][name+'_hit5']+=bool(rank and rank<=5)
        totals[group]['count']+=1;totals[group]['retrieved']+=result['retrieved'];results.append(result)
        if n%20==0: print(f'Probes {n}/{len(chosen)}',flush=True)
    report={'groups':{k:dict(v) for k,v in totals.items()},'results':results,'training_queries_sha256':sha256(a.training_queries),'ranker_sha256':sha256(a.ranker),'limitations':'Synthetic templates copy target titles, no human judgments. Scores use retrieved candidate order before admission gates; do not prove real search quality, conversion or retention.'}
    atomic_json(a.output,report)
    print(json.dumps(report['groups'],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
