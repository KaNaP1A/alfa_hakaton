"""Prepare isolated mixed training catalog and weak persona queries; no user data."""
from __future__ import annotations
import argparse
import ast
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from alfa_reco.bundle import atomic_json, load_bundle, sha256

REVISION = 'ccd36c1660fee9610d5262e7517d8397c343168b'
TAXONOMY = {
    'Финансы и налоги': ('финанс', 'налог', 'бюджет', 'бухгалтер', 'finance', 'financial', 'taxation', 'accounting', 'budget'),
    'Маркетинг и продажи': ('маркетинг', 'продаж', 'клиент', 'реклам', 'marketing', 'sales', 'customer', 'advertising'),
    'Команда и управление': ('команд', 'сотрудник', 'персонал', 'найм', 'leadership', 'management', 'employees', 'team'),
    'Технологии и данные': ('программир', 'нейросет', 'автоматизац', 'данных', 'python', 'data', 'technology', 'artificial intelligence', 'automation'),
    'Запуск и развитие бизнеса': ('предприним', 'стартап', 'бизнес', 'startup', 'business', 'entrepreneur'),
    'Право и договоры': ('правов', 'договор', 'закон', 'юридическ', 'legal', 'contract', 'law'),
}
ROLES = ('студент', 'начинающий предприниматель', 'владелец малого бизнеса', 'специалист по найму', 'руководитель команды', 'самозанятый', 'предприниматель 40 лет', 'человек старшего возраста', 'аналитик', 'новичок')
TEMPLATES = ('Я {role}. Хочу разобраться: {title}', 'Подскажите, пожалуйста, как изучить {title}? Я {role}.', 'Мне нужно быстро понять: {title}. Я {role}.', 'Объясните простыми словами {title}; я {role}.', 'Для работы нужна информация по теме {title}. Я {role}.', 'Привет, подскажи как разобраться с темой {title}? Я {role}.', 'Ищу практические материалы по теме «{title}». Я {role}.', 'Планирую изучить {title}; контекст: {role}.', 'Как начать разбираться в теме {title}? Мне это нужно как {role}.', 'Нужен материал по теме {title}, я {role}.')

def normalize(value):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', value).casefold()))

def inferred_tags(title, description):
    text = normalize(title + ' ' + description)
    result = []
    for tag, words in TAXONOMY.items():
        evidence = sorted({word for word in words if normalize(word) in text})
        if evidence: result.append({'tag': tag, 'evidence': evidence})
    return result

def make_corpus(base, hf_rows, sample_limit=1200):
    grouped = defaultdict(list)
    for row in base: grouped[(row['kind'], normalize(row['title']))].append(row)
    kept, quarantine = [], []
    for _, group in sorted(grouped.items()):
        group.sort(key=lambda x: (x.get('experiment_origin') is not None, x['entity_key']))
        kept.append(dict(group[0]))
        quarantine.extend({'entity_key':x['entity_key'],'retained_key':group[0]['entity_key'], 'reason':'same_kind_normalized_title_identity_not_verified'} for x in group[1:])
    used = {normalize(item['title']) for item in kept if item['kind']=='course'}
    hf_groups = defaultdict(list)
    for row in hf_rows:
        title=(row.get('title') or '').strip(); description=(row.get('Description') or '').strip(); url=(row.get('URL') or '').strip()
        if title and description and url.startswith('https://www.coursera.org/'): hf_groups[normalize(title)].append(row)
    candidates=[]; hf_duplicates=0
    for normalized, group in hf_groups.items():
        hf_duplicates+=len(group)-1
        group.sort(key=lambda x:(x.get('URL',''),x.get('Description',''))); row=group[0]
        if normalized in used: continue
        labels=inferred_tags(row['title'],row['Description'])
        if not labels: continue
        score=hashlib.sha256(('hf-select-42:'+normalized).encode()).hexdigest()
        candidates.append((score,normalized,row,labels))
    candidates.sort(key=lambda row:row[0])
    for _,normalized,row,labels in candidates[:sample_limit]:
        try: skills=ast.literal_eval(row.get('Skills') or '[]')
        except (ValueError,SyntaxError): skills=[]
        if not isinstance(skills,list): skills=[]
        skills=list(dict.fromkeys(x.strip() for x in skills if isinstance(x,str) and x.strip()))[:50]
        ident=hashlib.sha256(normalized.encode()).hexdigest()[:24]
        title,description=row['title'].strip(),row['Description'].strip()[:8000]
        kept.append({'entity_key':'course:hf-'+ident,'source_id':'hf-'+ident,'kind':'course','title':title,'description':description,'body':'','topics':[], 'tags':skills,'industries':[],'lessons':[],'search_text':title+' '+description,'access_type':'unknown','price_raw':None,'price_currency':None,'publication_status':'unknown','canonical_url':None,'source_url':None,'data_quality_flags':['external_training_only'],'experiment_origin':'huggingface_training_only','taxonomy_evidence':labels,'external_source':{'dataset':'azrai99/coursera-course-dataset','revision':REVISION,'license':'apache-2.0','url':row['URL']}})
    for row in kept:
        if row.get('experiment_origin') in {'public_snapshot','synthetic'}:
            evidence=inferred_tags(row['title'],row.get('description',''));row['taxonomy_evidence']=evidence
            row['tags']=list(dict.fromkeys(row.get('tags',[])+[x['tag'] for x in evidence]))
    keys=[x['entity_key'] for x in kept]
    if len(keys)!=len(set(keys)): raise ValueError('Duplicate entity keys')
    return kept,quarantine,{'base_total':len(base),'base_quarantined':len(quarantine),'hf_rows':len(hf_rows),'hf_title_duplicates':hf_duplicates,'hf_eligible':len(candidates),'hf_added':min(sample_limit,len(candidates))}

def assign_split(title):
    value=int(hashlib.sha256(('persona-split-42:'+normalize(title)).encode()).hexdigest()[:8],16)%100
    return 'train' if value<70 else 'validation' if value<85 else 'test'

def queries(catalog,protected,per_material=3):
    rows=[]; seen=set()
    for row in sorted(catalog,key=lambda r:r['entity_key']):
        if row['kind'] not in {'course','article','podcast','document'} or row['entity_key'] in protected: continue
        title=' '.join(row['title'].split())
        if len(title)<8 or len(title)>150: continue
        split=assign_split(title)
        for variant in range(per_material):
            seed=int(hashlib.sha256(f"persona-42:{row['entity_key']}:{variant}".encode()).hexdigest()[:12],16)
            role=ROLES[seed%len(ROLES)]; style=(seed//len(ROLES))%len(TEMPLATES); query=TEMPLATES[style].format(role=role,title=title); key=normalize(query)
            if key in seen or len(query)>300: continue
            seen.add(key)
            rows.append({'id':'pq-'+hashlib.sha256(key.encode()).hexdigest()[:20],'query':query,'target':row['entity_key'],'family':normalize(title),'split':split,'source':'template_persona_v1','persona':role,'style_id':style,'language':'ru_template_with_source_title','label_status':'weak_target_preference','synthetic':True,'origin':row.get('experiment_origin','backup')})
    return rows

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,default=Path('artifacts/offline_mixed_index_20261115_v1'))
    parser.add_argument('--hf',type=Path,default=Path('artifacts/external_courses/coursera_course_2024.csv'))
    parser.add_argument('--cases',type=Path,default=Path('evaluation/ensemble_cases_v2.json'))
    parser.add_argument('--observed-prices',type=Path,default=Path('experiments/alfa_public_courses.json'))
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--hf-limit',type=int,default=1200)
    args=parser.parse_args()
    if not 0<=args.hf_limit<=6645: raise ValueError('Invalid hf limit')
    _,manifest,base=load_bundle(args.base)
    with args.hf.open(encoding='utf-8-sig',newline='') as file: hf=list(csv.DictReader(file))
    catalog,quarantine,stats=make_corpus(base,hf,args.hf_limit)
    cases=json.loads(args.cases.read_text())['queries'];protected={j['entity_key'] for c in cases for j in c['judgments']}
    weak=queries(catalog,protected);families=defaultdict(set)
    for row in weak: families[row['family']].add(row['split'])
    if any(len(s)!=1 for s in families.values()): raise ValueError('Query families cross splits')
    bytitle=defaultdict(list)
    for row in catalog: bytitle[(row['kind'],normalize(row['title']))].append(row['entity_key'])
    observations=[]
    for row in json.loads(args.observed_prices.read_text())['courses']:
        matches=bytitle[('course',normalize(row['title']))]
        observations.append({'title':row['title'],'observed_price_rub':row['observed_price_rub'],'source':'public homepage observation','observed_at':'2026-11-15','candidate_entity_key':matches[0] if len(matches)==1 else None,'match_status':'exact_title_candidate_not_verified' if len(matches)==1 else 'unmatched_or_ambiguous','current_offer_verified':False})
    args.output.mkdir(parents=True,exist_ok=False);atomic_json(args.output/'catalog.json',catalog);atomic_json(args.output/'quarantine.json',quarantine);atomic_json(args.output/'observed_price_candidates.json',observations)
    with (args.output/'taxonomy_annotations.jsonl').open('x',encoding='utf-8') as f:
        for row in catalog:
            labels=inferred_tags(row['title'],row.get('description') or '')
            f.write(json.dumps({'entity_key':row['entity_key'],'labels':labels,'method':'keyword_heuristic_v1','status':'unverified'},ensure_ascii=False)+'\n')
    with (args.output/'persona_queries.jsonl').open('x',encoding='utf-8') as f:
        for row in weak: f.write(json.dumps(row,ensure_ascii=False)+'\n')
    report={'source_catalog_sha256':manifest['catalog_sha256'],'external_sha256':sha256(args.hf),'external_dataset':'azrai99/coursera-course-dataset','external_revision':REVISION,'external_license':'apache-2.0','catalog_sha256':sha256(args.output/'catalog.json'),'queries_sha256':sha256(args.output/'persona_queries.jsonl'),'taxonomy_sha256':sha256(args.output/'taxonomy_annotations.jsonl'),'stats':stats,'total_catalog':len(catalog),'query_splits':dict(Counter(x['split'] for x in weak)),'query_origins':dict(Counter(x['origin'] for x in weak)),'price_candidates':dict(Counter(x['match_status'] for x in observations)),'protected_judgment_ids':len(protected),'seed':42,'notice':'External courses and machine tags are training-only; persona/queries are synthetic and targets weak. Price observations are historical candidates, not verified offers.'}
    atomic_json(args.output/'manifest.json',report);print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
