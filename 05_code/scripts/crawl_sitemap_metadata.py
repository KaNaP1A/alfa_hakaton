"""Resumable collection of public item metadata from the owner's sitemap.

No accounts, lesson contents, file downloads or disallowed URLs are requested.
Only allowlisted metadata is stored; the user's product/backend verifies all rights.
"""
import argparse
import hashlib
import json
import sqlite3
import ssl
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from protego import Protego

if __package__:
    from scripts.collect_public_catalog import (
        AGENT,
        ORIGIN,
        MetadataParser,
        SameHostRedirect,
        fetch,
    )
else:
    from collect_public_catalog import AGENT, ORIGIN, MetadataParser, SameHostRedirect, fetch

KINDS = ('course', 'article', 'document', 'podcast')


class StateParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.chunks = []
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('id') == 'ng-state':
            self.count += 1
            self.inside = True

    def handle_data(self, data):
        if self.inside:
            self.chunks.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.inside:
            self.inside = False


class NoItemRedirect(SameHostRedirect):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(newurl, code, 'Item redirect not followed', headers, fp)


def valid_item(url, kind):
    p = urlsplit(url)
    parts = [x for x in p.path.split('/') if x]
    return (kind in KINDS and p.scheme == 'https' and p.netloc == 'kurs.alfabank.ru'
            and not p.query and not p.fragment and len(parts) == 2 and parts[0] == kind + 's')


def select_item(state, url, kind):
    slug = unquote(urlsplit(url).path.strip('/').split('/')[-1])
    matches = []
    for response in state.values():
        if not isinstance(response, dict) or not isinstance(response.get('u'), str):
            continue
        p = urlsplit(response['u'])
        if p.scheme != 'https' or p.netloc != 'kurs.alfabank.ru' or p.path != f'/api/public/courses/{kind}/list':
            continue
        body = response.get('b')
        if isinstance(body, list):
            matches.extend(item for item in body if isinstance(item, dict) and item.get('url') == slug)
    ids = {item.get('id') for item in matches if isinstance(item.get('id'), str) and item['id']}
    if len(ids) > 1:
        raise ValueError('Conflicting structured item IDs')
    return matches[-1] if matches and len(ids) == 1 else None


def parse_metadata(html, url, kind, observed_at):
    if not valid_item(url, kind):
        raise ValueError('Invalid item URL')
    page = MetadataParser()
    page.feed(html)
    state_parser = StateParser()
    state_parser.feed(html)
    item = None
    if state_parser.count > 1:
        raise ValueError('Multiple Angular state scripts')
    if state_parser.count == 1:
        state = json.loads(''.join(state_parser.chunks))
        if not isinstance(state, dict):
            raise ValueError('Invalid Angular state')
        item = select_item(state, url, kind)
    title = item.get('title') if item else None
    title_source = 'embedded_exact_slug' if title else 'h1' if page.h1 else 'og:title'
    title = title or ' '.join(' '.join(page.h1).split()) or page.metadata.get('og:title', '').strip()
    if not isinstance(title, str) or not title.strip():
        raise ValueError('Missing title')
    description = (item.get('description') if item else None) or page.metadata.get('og:description') or page.metadata.get('description')
    if description is not None and not isinstance(description, str):
        raise ValueError('Description must be text')
    item_id = item.get('id') if item else None
    return {'source_url': url, 'kind': kind, 'source_id': item_id,
            'entity_key': f'{kind}:{item_id}' if item_id else None,
            'title': title, 'title_source': title_source, 'description': description,
            'source_status_id_raw': item.get('statusId') if item else None,
            'source_noindex_raw': item.get('noIndex') if item else None,
            'source_published_raw': item.get('published') if item else None,
            'source_modified_raw': item.get('modified') if item else None,
            'source_is_public_raw': item.get('isPublic') if item else None,
            'source_is_closed_raw': item.get('isClosed') if item else None,
            'access_type': 'unknown', 'price_status': 'unknown', 'price_raw_meta': page.metadata.get('product:price:amount'),
            'currency_raw_meta': page.metadata.get('product:price:currency'),
            'purchase_verified': False, 'observed_at': observed_at,
            'source': 'public_page_html', 'html_sha256': hashlib.sha256(html.encode('utf-8')).hexdigest()}


def create_frontier(db, inventory, inventory_hash, robots_hash, parser_hash):
    db.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS frontier(url TEXT PRIMARY KEY,kind TEXT NOT NULL,state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS items(url TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS failures(url TEXT NOT NULL,error TEXT NOT NULL,observed_at TEXT NOT NULL);''')
    existing = dict(db.execute('SELECT key,value FROM meta'))
    if existing:
        if (existing.get('inventory_sha256') != inventory_hash
                or existing.get('robots_sha256') != robots_hash
                or existing.get('parser_sha256') != parser_hash):
            raise ValueError('Inventory, robots or parser changed: create a new output and review')
        return
    groups = {kind: [] for kind in KINDS}
    for row in inventory:
        kind, url = row.get('kind_hint'), row.get('url')
        if kind in KINDS and isinstance(url, str) and row.get('robots_allowed') is True and valid_item(url, kind):
            groups[kind].append(url)
    ordered = []
    for index in range(max((len(v) for v in groups.values()), default=0)):
        for kind in KINDS:
            if index < len(groups[kind]):
                ordered.append((groups[kind][index], kind, 'pending'))
    with db:
        db.executemany('INSERT INTO meta(key,value) VALUES (?,?)', [
            ('inventory_sha256', inventory_hash), ('robots_sha256', robots_hash),
            ('parser_sha256', parser_hash),
        ])
        db.executemany('INSERT OR IGNORE INTO frontier(url,kind,state) VALUES (?,?,?)', ordered)


def export_state(db, output):
    payloads = [row[0] for row in db.execute('SELECT payload FROM items ORDER BY rowid')]
    temp = output / 'materials.jsonl.tmp'
    temp.write_text(''.join(line + '\n' for line in payloads), encoding='utf-8')
    temp.replace(output / 'materials.jsonl')
    rows = [json.loads(line) for line in payloads]
    states = dict(db.execute('SELECT state,COUNT(*) FROM frontier GROUP BY state'))
    last_failure = db.execute('SELECT error,observed_at FROM failures ORDER BY rowid DESC LIMIT 1').fetchone()
    report = {'frontier': states, 'extracted': len(rows), 'by_kind': dict(Counter(r['kind'] for r in rows)),
              'with_source_id': sum(r['source_id'] is not None for r in rows),
              'without_description': sum(not (r['description'] or '').strip() for r in rows),
              'access_and_price': 'unknown; requires backend verification', 'coverage_verified': False,
              'last_failure': {'error': last_failure[0], 'observed_at': last_failure[1]} if last_failure else None,
              'limitations': 'Only public sitemap item pages and allowlisted metadata; no lesson contents, file downloads or user records. Sitemap coverage is not complete.'}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def crawl(inventory_path, output, ca_file, max_pages=30, delay=1.0):
    if max_pages < 1 or delay < 1:
        raise ValueError('Require at least one page and a delay of at least one second')
    raw_inventory = inventory_path.read_bytes()
    inventory_hash = hashlib.sha256(raw_inventory).hexdigest()
    parser_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    inventory = [json.loads(line) for line in raw_inventory.decode('utf-8').splitlines() if line.strip()]
    redirect = NoItemRedirect()
    context = ssl.create_default_context(cafile=str(ca_file))
    opener = urllib.request.build_opener(redirect, urllib.request.HTTPSHandler(context=context))
    robots, _ = fetch(opener, ORIGIN + '/robots.txt')
    robots_hash = hashlib.sha256(robots).hexdigest()
    policy = Protego.parse(robots.decode('utf-8', 'strict'))
    redirect.policy = policy
    delay = max(delay, policy.crawl_delay(AGENT) or policy.crawl_delay('*') or 0)
    rate = policy.request_rate(AGENT) or policy.request_rate('*')
    if rate and rate.requests > 0:
        delay = max(delay, rate.seconds / rate.requests)
    output.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output / 'checkpoint.sqlite') as db:
        create_frontier(db, inventory, inventory_hash, robots_hash, parser_hash)
        count = 0
        while count < max_pages:
            found = db.execute("SELECT url,kind FROM frontier WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
            if found is None:
                break
            url, kind = found
            try:
                if not policy.can_fetch(url, AGENT):
                    raise ValueError('URL forbidden by current robots.txt')
                time.sleep(delay)
                body, content_type = fetch(opener, url)
                if content_type != 'text/html':
                    raise ValueError('Unexpected content type')
                html = body.decode('utf-8', errors='strict')
                record = parse_metadata(html, url, kind, datetime.now(UTC).isoformat())
                with db:
                    db.execute('INSERT INTO items(url,payload) VALUES (?,?)', (url, json.dumps(record, ensure_ascii=False)))
                    db.execute("UPDATE frontier SET state='done' WHERE url=?", (url,))
                count += 1
                if count % 10 == 0:
                    print('Processed in this run:', count, flush=True)
            except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as error:
                with db:
                    db.execute('INSERT INTO failures(url,error,observed_at) VALUES (?,?,?)',
                               (url, f'{type(error).__name__}: {error}'[:500], datetime.now(UTC).isoformat()))
                report = export_state(db, output)
                print(json.dumps(report, ensure_ascii=False, indent=2))
                raise
        return export_state(db, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ca-file', type=Path, required=True)
    parser.add_argument('--max-pages', type=int, default=30)
    parser.add_argument('--delay', type=float, default=1.0)
    args = parser.parse_args()
    print(json.dumps(crawl(args.inventory, args.output, args.ca_file, args.max_pages, args.delay), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
