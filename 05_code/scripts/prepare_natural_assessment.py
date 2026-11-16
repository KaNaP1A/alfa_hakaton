"""Record the assistant's provisional review and prepare a human review sheet.

Ratings are deliberately not human-verification flags. Candidate order follows
an independently generated blinded pool; input grades are by pool position.
"""
import argparse
import json
from pathlib import Path
from alfa_reco.bundle import atomic_json, sha256

# Provisional assessments against title and description, not actual course content.
GRADES = {
    'n01': [1, 1, 3, 1, 1], 'n02': [1, 2, 0, 1, 1, 3, 0],
    'n03': [1, 3, 2, 3, 3], 'n04': [0, 0, 0],
    'n05': [1, 0, 1, 1, 3, 0], 'n06': [0, 0, 2, 3, 0],
    'n07': [0], 'n08': [2, 2, 3, 2, 0], 'n09': [1, 2, 1, 2, 3, 1],
    'n10': [3, 2], 'n11': [0, 0, 2, 0, 3], 'n12': [0, 0, 0, 2, 0, 0, 1],
    'n13': [2, 0, 0, 2, 0], 'n14': [0, 0, 0], 'n15': [0, 3, 0, 1, 0, 0, 0],
    'n16': [0, 2, 3, 2], 'n17': [2, 1, 0, 2, 0, 0], 'n18': [1, 1, 0, 1, 1],
    'n19': [0, 3, 3, 0, 0, 2], 'n20': [1, 1, 2, 3, 1],
}
# Tie assessments to the exact blinded pool; no grades may silently shift after regeneration.
EXPECTED_POOL_SHA256 = 'bfcbcbf25a4e6a484f189977820c926d05e9e13a5fd7874d70d3d477b6105ce4'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pool',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if sha256(a.pool) != EXPECTED_POOL_SHA256: raise ValueError('Pool differs from reviewed candidate order')
    if a.output.exists(): raise ValueError('Output must be new')
    pool=[json.loads(x) for x in a.pool.read_text().splitlines()]
    if set(GRADES)!={x['id'] for x in pool}: raise ValueError('Missing or extra query ratings')
    holdout={c['entity_key'] for row in pool if row['split']!='train' for c in row['candidates']}
    assessed=[]; train=[]; review=['# Независимая проверка релевантности', '',
        'Запросы придуманы ассистентом, карточки перемешаны, его оценки здесь не показаны.',
        'Замените каждый прочерк после «Оценка человека» на 0, 1, 2, 3 или ?: 0 — не подходит, 1 — общая тема, 2 — частично отвечает, 3 — прямо отвечает, ? — не знаю.',
        'Допустимо пропускать карточки. В описании может быть только часть текста, поэтому при недостатке данных выбирайте ?. Сохраните файл и сообщите, когда закончите.', '']
    for row in pool:
        grades=GRADES[row['id']]
        if len(grades)!=len(row['candidates']): raise ValueError('Candidate count mismatch')
        judgments=[]
        review.extend([f"## {row['id']} — {row['query']}", ''])
        for candidate,grade in zip(row['candidates'],grades,strict=True):
            assessed.append({'query_id':row['id'],'entity_key':candidate['entity_key'],'grade':grade,
                             'assessor':'assistant_provisional','human_verified':False})
            if candidate['entity_key'] not in holdout:
                judgments.append({'entity_key':candidate['entity_key'],'grade':grade})
            review.extend([f"- Оценка человека: ___ — **{candidate['title']}** (`{candidate['entity_key']}`)",
                           f"  {candidate['description'][:400].replace(chr(10),' ')}"])
        review.append('')
        if row['split']=='train' and len({x['grade'] for x in judgments})>=2:
            train.append({'id':'natural:'+row['id'],'family':'natural:'+row['family'],
                          'split':'train','query':row['query'],'judgments':judgments})
    a.output.mkdir(parents=True)
    (a.output/'assistant_judgments.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in assessed))
    (a.output/'review.md').write_text('\n'.join(review))
    atomic_json(a.output/'assistant_train.json',{'assessor':'assistant_provisional_not_human','pool_sha256':sha256(a.pool),'queries':train})
    atomic_json(a.output/'heldout_ids.json',sorted(holdout))
    atomic_json(a.output/'manifest.json',{'pool_sha256':sha256(a.pool),'queries':len(pool),'pairs':len(assessed),'train_queries':len(train),'heldout_ids':len(holdout),'human_verified':False})
    print(json.dumps({'pairs':len(assessed),'train_ids':[x['id'] for x in train],'heldout_ids':len(holdout)},ensure_ascii=False))

if __name__=='__main__': main()
