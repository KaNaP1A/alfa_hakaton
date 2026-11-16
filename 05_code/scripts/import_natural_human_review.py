"""Import explicitly entered human ratings from the blinded Markdown review sheet."""
import argparse
import json
import re
from pathlib import Path
from alfa_reco.bundle import atomic_json, sha256

HEADER = re.compile(r'^## (n\d+) — ')
RATING = re.compile(r'^- Оценка человека: (___|[0-3?]) — .* \(`([^`]+)`\)$')


def parse_review(text, pool):
    allowed={(row['id'],c['entity_key']) for row in pool for c in row['candidates']}
    seen=set();ratings=[];query=None
    for line in text.splitlines():
        header=HEADER.match(line)
        if header: query=header.group(1);continue
        if line.startswith('- Оценка человека:'):
            match=RATING.fullmatch(line)
            if not match or query is None: raise ValueError('Invalid review line or missing query header')
            value,key=match.groups();pair=(query,key)
            if pair not in allowed or pair in seen: raise ValueError('Unknown or duplicate reviewed item')
            seen.add(pair)
            if value not in {'___','?'}:
                ratings.append({'query_id':query,'entity_key':key,'grade':int(value),
                                'assessor':'human_declared','human_review_claimed':True,
                                'human_verified':False})
    if seen != allowed: raise ValueError('Missing candidate lines from review sheet')
    return ratings


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--review',type=Path,required=True)
    p.add_argument('--pool',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists(): raise ValueError('Output must be new')
    pool=[json.loads(x) for x in a.pool.read_text().splitlines()]
    ratings=parse_review(a.review.read_text(),pool)
    a.output.mkdir(parents=True)
    (a.output/'human_judgments.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in ratings))
    atomic_json(a.output/'manifest.json',{'review_sha256':sha256(a.review),'pool_sha256':sha256(a.pool),
                'ratings':len(ratings),'unresolved':sum(len(r['candidates']) for r in pool)-len(ratings),
                'notice':'Human assessment is user-declared, not independently identity-verified.'})
    print(json.dumps({'ratings':len(ratings),'unresolved':sum(len(r['candidates']) for r in pool)-len(ratings)}))

if __name__=='__main__':main()
