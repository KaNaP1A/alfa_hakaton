"""Trace a few known, manually identified targets through retrieval and admission."""
import argparse
import json
from pathlib import Path
from alfa_reco.bundle import atomic_json, sha256
from alfa_reco.search import SearchEngine

TARGETS = {
    'n04': 'podcast:296e7be7-e4ff-4ed9-9302-7f3dacad8d8b',
    'n07': 'course:offline-b5b7356da03278b8859d6147',
    'n14': 'article:a4d9713c-9e28-4492-bd8b-267982847265',
}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog',type=Path,required=True)
    p.add_argument('--queries',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists(): raise ValueError('Output already exists')
    queries={r['id']:r for r in json.loads(a.queries.read_text())['queries']}
    engine=SearchEngine(a.catalog);backend=engine.relevance_backend()
    indices={r['entity_key']:i for i,r in enumerate(engine.catalog)}
    rows=[]
    for qid,key in TARGETS.items():
        i=indices[key];query=queries[qid]['query'];prepared=backend.prepare(query)
        ranked,_=backend.score(prepared);result=engine.search(query,mode='relevance',top=5)
        support=backend.support(prepared,i,conflict=backend.conflict(prepared,i))
        rows.append({'id':qid,'query':query,'target':key,'title':engine.catalog[i]['title'],
                     'description':engine.catalog[i].get('description',''),
                     'in_retrieved_candidates':i in prepared['candidates'],
                     'candidate_rank':ranked.index(i)+1 if i in ranked else None,
                     'support':support,'in_shown_top5':key in {x['entity_key'] for x in result['results']},
                     'displayed_titles':[x['title'] for x in result['results']],
                     'retrieval_diagnostics':result['retrieval_diagnostics']})
        print(qid,rows[-1]['in_retrieved_candidates'],rows[-1]['candidate_rank'],support['admitted'],flush=True)
    atomic_json(a.output,{'catalog_sha256':engine.manifest['catalog_sha256'],'queries_sha256':sha256(a.queries),
                          'rows':rows,'limitations':'Three assistant-identified targets; no independent human review or full catalog recall estimate.'})

if __name__=='__main__':main()
