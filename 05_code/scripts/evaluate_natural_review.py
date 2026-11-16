"""Compare ordering of a fixed, fully assessed candidate pool; never treats unknown as zero."""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from catboost import CatBoostRanker
from alfa_reco.bundle import atomic_json, sha256
from alfa_reco.search import SearchEngine


def scored_metrics(ranked, grades, k=5):
    """NDCG@k among this assessed pool; None when no grade >= 2 exists."""
    if not any(grade >= 2 for grade in grades.values()):
        return None
    def gain(grade): return (2**grade-1)
    dcg=sum(gain(grades[key])/math.log2(i+2) for i,key in enumerate(ranked[:k]))
    ideal=sorted(grades.values(),reverse=True)[:k]
    idcg=sum(gain(grade)/math.log2(i+2) for i,grade in enumerate(ideal))
    first=next((i+1 for i,key in enumerate(ranked[:k]) if grades[key]>=2),None)
    return {'ndcg5':dcg/idcg,'mrr5':1/first if first else 0.0,
            'judged_relevant_recall5':sum(grades[key]>=2 for key in ranked[:k])/sum(x>=2 for x in grades.values())}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog',type=Path,required=True)
    p.add_argument('--pool',type=Path,required=True)
    p.add_argument('--judgments',type=Path,required=True)
    p.add_argument('--candidate',action='append',default=[],metavar='NAME=PATH')
    p.add_argument('--split',choices=['train','validation','test'],required=True)
    p.add_argument('--skip-incomplete',action='store_true',
                   help='Exclude incompletely assessed queries instead of treating missing grades as zero')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists(): raise ValueError('Output already exists')
    all_rows=[json.loads(x) for x in a.pool.read_text().splitlines()]
    rows=[r for r in all_rows if r['split']==a.split]
    labels=defaultdict(dict)
    for line in a.judgments.read_text().splitlines():
        j=json.loads(line)
        if j['entity_key'] in labels[j['query_id']] or type(j['grade']) is not int or not 0<=j['grade']<=3:
            raise ValueError('Invalid or duplicate assessment')
        labels[j['query_id']][j['entity_key']]=j['grade']
    engine=SearchEngine(a.catalog); backend=engine.relevance_backend()
    models={'baseline':backend.model}; hashes={}
    for spec in a.candidate:
        name,sep,path=spec.partition('=')
        if not sep or name in models: raise ValueError('Expected unique NAME=PATH')
        model=CatBoostRanker();model.load_model(path);models[name]=model;hashes[name]=sha256(Path(path))
    result=[]; incomplete=[]
    for row in rows:
        grades=labels[row['id']]
        if set(grades)!={c['entity_key'] for c in row['candidates']}:
            if a.skip_incomplete:
                incomplete.append(row['id']);continue
            raise ValueError('Pool must be fully assessed')
        prepared=backend.prepare(row['query'])
        by_model={}
        for name,model in models.items():
            backend.model=model
            ranked,_=backend.score(prepared)
            projected=[engine.catalog[i]['entity_key'] for i in ranked if engine.catalog[i]['entity_key'] in grades]
            if set(projected)!=set(grades):
                raise ValueError('Some assessed candidates were not retrieved for this query')
            by_model[name]={'metrics':scored_metrics(projected,grades),'ranked_pool':projected}
        result.append({'id':row['id'],'family':row['family'],'models':by_model,'max_grade':max(grades.values(),default=0)})
        print('Assessed',row['id'],flush=True)
    summary={}
    for name in models:
        values=[row['models'][name]['metrics'] for row in result if row['models'][name]['metrics'] is not None]
        summary[name]={'scored_queries':len(values),'no_assessed_relevant':len(result)-len(values)}
        for field in ('ndcg5','mrr5','judged_relevant_recall5'):
            summary[name][field]=mean(x[field] for x in values) if values else None
    report={'split':a.split,'queries':len(rows),'excluded_incomplete_queries':incomplete,
            'catalog_sha256':engine.manifest['catalog_sha256'],
            'pool_sha256':sha256(a.pool),'judgments_sha256':sha256(a.judgments),'ranker_sha256':hashes,
            'summary':summary,'rows':result,
            'limitations':'Small assistant-authored queries and assistant-assessed labels, not independent humans or real-user data. Fixed pool is top candidates of two earlier rankers; ranks measured within pool before admission gates; scores do not measure retrieval or real sales.'}
    atomic_json(a.output,report);print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
