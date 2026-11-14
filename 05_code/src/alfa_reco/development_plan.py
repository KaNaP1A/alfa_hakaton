"""Explainable next steps from explicit activity; not a learned prerequisite graph."""
from .eligibility import USER_KINDS
from .personalization import CATEGORIES, facets, recommend, title_subjects
from .profile_metadata import (
    EXPERIENCE,
    STAGES,
    experience_evidence,
    industry_matches,
    stage_evidence,
)


def development_plan(
    catalog, categories, viewed, completed, vectors=None, *, started=None,
    interested=None, goal_candidate_keys=None, preferred_kinds=None, industry=None,
    business_stage=None, experience=None, dedupe_titles=True,
):
    started = [] if started is None else started
    interested = [] if interested is None else interested
    preferred_kinds = [] if preferred_kinds is None else preferred_kinds
    by_id = {item['entity_key']: item for item in catalog}
    indices = {item['entity_key']: i for i, item in enumerate(catalog)}
    generic = {'шаг', 'модел', 'часть', 'основ', 'совет', 'пут', 'перв', 'нов', 'успех'}
    subjects = {item['entity_key']: title_subjects(item['title']) - generic for item in catalog}
    for values in (categories, viewed, completed, started, interested):
        if not isinstance(values, list) or len(values) > 50:
            raise ValueError('Profile fields must be lists with at most 50 entries')
        if any(not isinstance(value, str) for value in values):
            raise ValueError('Profile entries must be strings')
    if len(categories) > len(CATEGORIES) or any(c not in CATEGORIES for c in categories):
        raise ValueError('Unknown interest category')
    if len(set(viewed + completed + started + interested)) > 50:
        raise ValueError('At most 50 distinct activity materials are supported')
    if any(key not in by_id or by_id[key]['kind'] not in USER_KINDS
           for key in viewed + completed + started + interested):
        raise ValueError('Activity material is not in this catalog')
    if any(by_id[key]['kind'] != 'course' for key in completed + started):
        raise ValueError('Only a course can be marked started or completed')
    if not isinstance(preferred_kinds, list) or any(
        not isinstance(k, str) or k not in USER_KINDS for k in preferred_kinds
    ):
        raise ValueError('Invalid preferred material types')
    if industry is not None and (not isinstance(industry, str) or not industry.strip()):
        raise ValueError('Invalid industry')
    if business_stage is not None and (not isinstance(business_stage, str) or business_stage not in STAGES):
        raise ValueError('Invalid business stage')
    if experience is not None and (not isinstance(experience, str) or experience not in EXPERIENCE):
        raise ValueError('Invalid experience')
    if type(dedupe_titles) is not bool:
        raise ValueError('dedupe_titles must be a boolean')
    if goal_candidate_keys is not None and (
        not isinstance(goal_candidate_keys, (set, frozenset))
        or not goal_candidate_keys <= set(by_id)
    ):
        raise ValueError('Invalid goal candidates')
    excluded = set(viewed + completed + started + interested)
    excluded_titles = {' '.join(by_id[key]['title'].casefold().split()) for key in excluded}
    profile_mode = (bool(started or interested or preferred_kinds or industry or business_stage or experience)
                    or goal_candidate_keys is not None or not dedupe_titles)
    result = {'method': 'activity_profile_plan_v2' if profile_mode else 'activity_content_plan_v1', 'status': 'needs_activity', 'steps': [],
              'notice': 'Это предлагаемый порядок изучения, а не обязательная программа. Завершение курса не подтверждает освоение навыков.'}
    if not excluded:
        return result
    # Repeated actions do not multiply interest. Completed courses have a stronger
    # weight; recency is only list order, never a fabricated timestamp.
    anchors = []
    added = set()
    for values, signal in ((completed, 'completed'), (started, 'started'),
                           (interested, 'interested'), (viewed, 'viewed')):
        for key in reversed(values):
            if key not in added:
                anchors.append((key, signal))
                added.add(key)
    scores, candidates, evidence = {}, {}, {}
    for position, (key, signal) in enumerate(anchors[:20]):
        source = by_id[key]
        for rank, item in enumerate(recommend(catalog, [], [key], limit=20, vectors=vectors)):
            target = item['entity_key']
            if (target in excluded or (dedupe_titles and ' '.join(item['title'].casefold().split()) in excluded_titles)
                    or (goal_candidate_keys is not None and target not in goal_candidate_keys)):
                continue
            shared = facets(source) & facets(by_id[target])
            overlap = subjects[key] & subjects[target]
            lexical = len(overlap) >= 2 or bool(overlap and shared)
            cosine = float(vectors[indices[key]] @ vectors[indices[target]]) if vectors is not None else None
            if cosine is None:
                grounded = lexical
            else:
                grounded = (lexical and cosine >= .78) or (bool(shared) and cosine >= .84) or cosine >= .90
            if not grounded:
                continue
            strength = {'completed': 3.0, 'started': 2.0, 'interested': 1.5, 'viewed': 1.0}[signal]
            weight = strength / (1 + position * .15) / (rank + 1)
            scores[target] = scores.get(target, 0) + weight
            candidates[target] = item
            evidence.setdefault(target, []).append({
                'entity_key': key, 'title': source['title'], 'signal': signal,
                'shared_topics_or_tags': sorted(facets(source) & facets(by_id[target])),
                'reason': item['reason'], 'weight': weight,
            })
    preferences = {topic for c in categories for topic in CATEGORIES[c][1]}
    # Interests refine activity-grounded candidates; they cannot invent an unrelated step.
    for key in scores:
        if facets(by_id[key]) & preferences:
            scores[key] *= 1.15
        if by_id[key]['kind'] in preferred_kinds:
            scores[key] *= 1.1
        if industry_matches(industry, by_id[key]):
            scores[key] *= 1.1
        if experience_evidence(experience, by_id[key]):
            scores[key] *= 1.05
        if stage_evidence(business_stage, by_id[key]):
            scores[key] *= 1.05
    remaining = sorted(scores, key=lambda key: (-scores[key], key))
    selected_titles = set()
    for index in range(3):
        if dedupe_titles:
            remaining = [key for key in remaining if ' '.join(by_id[key]['title'].casefold().split()) not in selected_titles]
        if not remaining:
            break
        key = remaining[0]
        # A relevant practical resource may follow the first learning resource.
        if index == 1 and result['steps'][0]['material']['kind'] not in {'document', 'calculator'}:
            key = next((candidate for candidate in remaining
                        if by_id[candidate]['kind'] in {'document', 'calculator'}
                        and scores[candidate] >= scores[key] * .6), key)
        item = candidates[key]
        source = max(evidence[key], key=lambda row: row['weight'])
        prefixes = {
            'completed': f'Вы отметили курс «{source["title"]}» завершённым.',
            'started': f'Вы отметили, что начали курс «{source["title"]}».',
            'interested': f'Вы отметили интерес к материалу «{source["title"]}».',
            'viewed': f'Вы отметили просмотр материала «{source["title"]}». Просмотр — сигнал интереса, а не освоения темы.',
        }
        prefix = prefixes[source['signal']]
        common = source['shared_topics_or_tags']
        connection = (' В каталоге у них общие темы или теги: ' + ', '.join('«' + t + '»' for t in common[:3]) + '.'
                      if common else ' ' + source['reason'] + '.')
        practical = item['kind'] in {'document', 'calculator'}
        result['steps'].append({
            'number': index + 1, 'title': 'Попробовать на практике' if practical else ('Продолжить тему' if index == 0 else 'Рассмотреть следующий материал'),
            'material': item, 'why': prefix + connection,
            'action': ('Откройте материал и проверьте, подходит ли он для вашей рабочей задачи.' if practical
                       else 'Посмотрите описание и выберите вопрос, который хотите разобрать при изучении.'),
            'order_reason': ('Начинаем с наиболее выраженной связи с вашей историей.' if index == 0 else
                             'После знакомства с темой предлагаем связанный практический материал.' if practical and index == 1 else
                             'Продолжаем подборку связанным материалом; предыдущий шаг не является обязательным условием.'),
            'evidence': {k: v for k, v in source.items() if k not in {'weight', 'reason'}},
            **({'profile_matches': {
                'preferred_kind': item['kind'] in preferred_kinds,
                'industry': industry_matches(industry, by_id[key]),
                'experience': experience_evidence(experience, by_id[key]),
                'business_stage': stage_evidence(business_stage, by_id[key]),
            }} if preferred_kinds or industry or experience or business_stage else {}),
        })
        selected_titles.add(' '.join(item['title'].casefold().split()))
        remaining.remove(key)
    result['status'] = 'ready' if len(result['steps']) == 3 else 'partial' if result['steps'] else 'insufficient_evidence'
    return result
