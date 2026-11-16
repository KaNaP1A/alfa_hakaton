"""Run the unified backend and real recommender on an isolated temporary database."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from config.settings import Settings
from schemas.requests import CatalogImport

ROOT = Path(__file__).absolute().parent.parent


def main() -> None:
    catalog = ROOT / 'models/unified'
    state = json.loads((catalog / 'ACTIVE.json').read_text())
    unified = catalog / state['catalog']
    generation = state['generation']
    original_root = ROOT / 'models/runtime/catalog'
    old_generation = json.loads((original_root / 'CURRENT.json').read_text())['generation']
    original = json.loads((original_root / old_generation / 'catalog.json').read_text())
    key = 'course:a25c8282-94c7-458e-abf6-9fbd7b996ef7'
    row = next(item for item in original if item['entity_key'] == key)
    source_cards = json.loads((ROOT / 'data/demo_catalog.json').read_text())['items']
    backup_webinars = {item['historical_entity_key'] for item in source_cards
                       if item['origin'] == 'historical_backup' and item['kind'] == 'webinar'}
    fixtures = [row] + [item for item in original if item['entity_key'] in backup_webinars]
    checks = []
    with tempfile.TemporaryDirectory(prefix='alfa-unified-check-') as temp:
        app = create_app(Settings(database_url='sqlite:///' + str(Path(temp) / 'test.sqlite3'),
                                  catalog_source='imported', reco_mode='python',
                                  reco_catalog=str(unified), unified_catalog=str(unified)))
        with TestClient(app) as client:
            with app.state.uow_factory() as uow:
                uow.catalog.import_catalog(CatalogImport.model_validate({
                    'generation': generation, 'materials': [{
                        'entity_key': item['entity_key'], 'kind': item['kind'], 'title': item['title'],
                        'description': item.get('description', ''), 'topics': item.get('topics', []),
                        'published': True, 'access': 'public',
                    } for item in fixtures]}))
                uow.commit()
            assert client.get('/ready').status_code == 200
            auth = client.post('/api/v1/auth/register', json={
                'username': 'unified-test', 'password': 'temporary-password-123'})
            assert auth.status_code == 201, auth.text
            client.headers['Authorization'] = 'Bearer ' + auth.json()['access_token']
            for kind, minimum in [('course', 100), ('webinar', 9), ('calculator', 7), ('lesson', 12)]:
                response = client.get('/api/v1/catalog', params={'kind': kind, 'limit': 50})
                assert response.status_code == 200, response.text
                payload = response.json()
                assert payload['generation'] == generation and payload['total'] >= minimum, (kind, payload['total'])
                assert len({item['entity_key'] for item in payload['items']}) == len(payload['items'])
                checks.append({'scenario': 'catalog_' + kind, 'count': payload['total']})
            lessons = client.get('/api/v1/catalog', params={'kind': 'lesson'}).json()['items']
            assert all(x['price']['status'] == 'conditional' and not x['access_verified'] for x in lessons)
            courses = client.get('/api/v1/catalog', params={'kind': 'course', 'limit': 50}).json()['items']
            unverified = next(item for item in courses if not item['access_verified'])
            completion = client.post('/api/v1/me/events', json={'generation': generation,
                'event_id': 'unverified-completion', 'entity_key': unverified['entity_key'],
                'action': 'completed'})
            assert completion.status_code == 403, completion.text
            checks.append({'scenario': 'unverified_course_completion_rejected'})
            search = client.get('/api/v1/search', params={'q': 'Команда практический урок', 'kind': 'lesson'})
            assert search.status_code == 200 and search.json()['results'], search.text
            checks.append({'scenario': 'lesson_search', 'results': len(search.json()['results'])})
            directory = client.get('/api/v1/interests')
            assert directory.status_code == 200, directory.text
            team = next(c for c in directory.json()['categories'] if c['id'] == 'team')
            topics = [t['value'] for t in team['topics']]
            assert topics, directory.text
            selected = topics[:2]
            profile = client.put('/api/v1/me/profile', json={'categories': ['team'], 'selected_facets': selected})
            assert profile.status_code == 200, profile.text
            recommendations = client.post('/api/v1/recommend', json={'generation': generation})
            assert recommendations.status_code == 200 and recommendations.json()['results'], recommendations.text
            results = recommendations.json()['results']
            assert all(set(x['topics']).intersection(selected) for x in results), (selected, results)
            first = results[0]['entity_key']
            event = client.post('/api/v1/me/events', json={'generation': generation, 'event_id': 'one', 'entity_key': first, 'action': 'viewed'})
            assert event.status_code == 201, event.text
            followup = client.post('/api/v1/recommend', json={'generation': generation})
            assert followup.status_code == 200 and all(x['entity_key'] != first for x in followup.json()['results'])
            checks.append({'scenario': 'multi_topic_and_history', 'topics': len(selected), 'results': len(results)})
            goal = client.put('/api/v1/me/profile', json={'categories': ['team'], 'goal': 'как управлять командой'})
            assert goal.status_code == 200, goal.text
            rec = client.post('/api/v1/recommend', json={'generation': generation})
            assert rec.status_code == 200 and rec.json()['results'], rec.text
            checks.append({'scenario': 'goal_recommendations', 'results': len(rec.json()['results'])})
            combined = client.put('/api/v1/me/profile', json={'categories': ['team'], 'selected_facets': selected, 'goal': 'как управлять командой'})
            assert combined.status_code == 200, combined.text
            combined_rec = client.post('/api/v1/recommend', json={'generation': generation})
            assert combined_rec.status_code == 200 and combined_rec.json()['results'], combined_rec.text
            assert all(set(x['topics']).intersection(selected) for x in combined_rec.json()['results'])
            assert all(x['entity_key'] != first for x in combined_rec.json()['results'])
            checks.append({'scenario': 'goal_topics_and_history', 'results': len(combined_rec.json()['results'])})
            plan = client.post('/api/v1/development-plan', json={'generation': generation})
            assert plan.status_code == 200, plan.text
            checks.append({'scenario': 'learning_plan', 'status': plan.json()['status'], 'steps': len(plan.json()['steps'])})
            assert client.post('/api/v1/auth/logout').status_code == 204
    print(json.dumps({'status': 'passed', 'generation': generation, 'checks': checks}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
