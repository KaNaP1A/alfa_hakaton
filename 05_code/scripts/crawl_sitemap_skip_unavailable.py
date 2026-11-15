"""Continue a verified sitemap crawl while recording unavailable individual pages.

Site-wide throttling, certificate/robots changes, recurring service failures and
metadata parsing errors remain stopping conditions. Does not fetch lesson pages.
"""
import argparse
import hashlib
import json
import re
import sqlite3
import ssl
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from protego import Protego

if __package__:
    from scripts import crawl_sitemap_metadata as base
    from scripts.collect_public_catalog import AGENT, ORIGIN, ResponseTooLarge, fetch
else:
    import crawl_sitemap_metadata as base
    from collect_public_catalog import AGENT, ORIGIN, ResponseTooLarge, fetch

# Per-page access errors can be recorded and skipped. A 429, 503 or a TLS
# failure can indicate a site-wide restriction and must not be skipped.
PAGE_CODES = set(range(300, 500)) - {429}
TRANSIENT_CODES = {500, 502, 504}
STOP_CODES = {429, 503}
MAX_CONSECUTIVE_RESTRICTIONS = 3


def previous_missing(db):
    """Use the recorded 404/410 evidence for the pending page; avoid requesting it again."""
    pending = db.execute("SELECT url FROM frontier WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
    if not pending:
        return False
    failure = db.execute('SELECT error FROM failures WHERE url=? ORDER BY rowid DESC LIMIT 1', pending).fetchone()
    match = re.match(r'^HTTPError: HTTP Error (404|410):', failure[0]) if failure else None
    if not match:
        return False
    with db:
        db.execute('UPDATE frontier SET state=? WHERE url=? AND state=?',
                   (f'skipped_http_{match.group(1)}', pending[0], 'pending'))
    return True


def classify(error):
    if isinstance(error, urllib.error.HTTPError):
        if error.code in STOP_CODES:
            return None, True
        if error.code in PAGE_CODES:
            # Consecutive denied requests can be a site-wide access restriction.
            return f'skipped_http_{error.code}', error.code in {401, 403}
        if error.code in TRANSIENT_CODES:
            return f'skipped_http_{error.code}', True
        return None, True
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, (ssl.SSLError, ConnectionRefusedError, ConnectionResetError)):
        return None, True
    if isinstance(reason, TimeoutError):
        return 'skipped_timeout', True
    return None, True


def crawl(inventory_path, output, ca_file, max_pages=2000, delay=1.5):
    if max_pages < 1 or delay < 1:
        raise ValueError('Require at least one page and a delay of at least one second')
    raw_inventory = inventory_path.read_bytes()
    inventory_hash = hashlib.sha256(raw_inventory).hexdigest()
    parser_hash = hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest()
    inventory = [json.loads(line) for line in raw_inventory.decode('utf-8').splitlines() if line.strip()]
    redirect = base.NoItemRedirect()
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
    with closing(sqlite3.connect(output / 'checkpoint.sqlite')) as db:
        base.create_frontier(db, inventory, inventory_hash, robots_hash, parser_hash)
        if previous_missing(db):
            print('Previously recorded missing page marked unavailable; continuing.', flush=True)
        attempts = 0
        consecutive_restrictions = 0
        try:
            while attempts < max_pages:
                found = db.execute("SELECT url,kind FROM frontier WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
                if found is None:
                    break
                url, kind = found
                if not policy.can_fetch(url, AGENT) or not base.valid_item(url, kind):
                    raise ValueError('URL forbidden by robots.txt or invalid item URL')
                try:
                    time.sleep(delay)
                    attempts += 1
                    body, content_type = fetch(opener, url)
                    if content_type != 'text/html':
                        raise ValueError('Unexpected content type; stopping for review')
                    record = base.parse_metadata(body.decode('utf-8', 'strict'), url, kind,
                                                 datetime.now(UTC).isoformat())
                    with db:
                        db.execute('INSERT INTO items(url,payload) VALUES (?,?)',
                                   (url, json.dumps(record, ensure_ascii=False)))
                        db.execute("UPDATE frontier SET state='done' WHERE url=?", (url,))
                    consecutive_restrictions = 0
                except (urllib.error.URLError, TimeoutError) as error:
                    state, restricted = classify(error)
                    consecutive_restrictions = consecutive_restrictions + 1 if restricted else 0
                    with db:
                        db.execute('INSERT INTO failures(url,error,observed_at) VALUES (?,?,?)',
                                   (url, f'{type(error).__name__}: {error}'[:500], datetime.now(UTC).isoformat()))
                        if state and consecutive_restrictions < MAX_CONSECUTIVE_RESTRICTIONS:
                            db.execute('UPDATE frontier SET state=? WHERE url=?', (state, url))
                    if state is None or consecutive_restrictions >= MAX_CONSECUTIVE_RESTRICTIONS:
                        raise
                    print(f'Page unavailable ({state}); recorded and skipped.', flush=True)
                except ResponseTooLarge as error:
                    with db:
                        db.execute('INSERT INTO failures(url,error,observed_at) VALUES (?,?,?)',
                                   (url, f'{type(error).__name__}: {error}', datetime.now(UTC).isoformat()))
                        db.execute("UPDATE frontier SET state='skipped_too_large' WHERE url=?", (url,))
                    consecutive_restrictions = 0
                    print('Page exceeded size limit; recorded and skipped.', flush=True)
                if attempts % 10 == 0:
                    print('Processed or skipped in this run:', attempts, flush=True)
        except (Exception, KeyboardInterrupt):
            print(json.dumps(base.export_state(db, output), ensure_ascii=False, indent=2), flush=True)
            raise
        return base.export_state(db, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ca-file', type=Path, required=True)
    parser.add_argument('--max-pages', type=int, default=2000)
    parser.add_argument('--delay', type=float, default=1.5)
    args = parser.parse_args()
    print(json.dumps(crawl(args.inventory, args.output, args.ca_file, args.max_pages, args.delay),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
