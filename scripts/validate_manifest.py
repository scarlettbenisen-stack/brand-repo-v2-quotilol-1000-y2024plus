#!/usr/bin/env python3
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
MANIFEST = BASE / 'input' / 'manifest.json'

VALID_STATUS = {'pending', 'ok', 'rejected'}
ID_RE = re.compile(r'^\d{5,30}$')


def main() -> int:
    if not MANIFEST.exists():
        print('ERROR: input/manifest.json introuvable')
        return 1

    data = json.loads(MANIFEST.read_text())
    items = data.get('items', [])
    if not isinstance(items, list):
        print('ERROR: manifest.items doit être une liste')
        return 1

    seen = set()
    errors = []

    for i, item in enumerate(items, start=1):
        tid = str(item.get('tweet_id', ''))
        url = str(item.get('url', ''))
        status = str(item.get('status', 'pending'))

        if not ID_RE.match(tid):
            errors.append(f'[{i}] tweet_id invalide: {tid!r}')
        if tid in seen:
            errors.append(f'[{i}] tweet_id dupliqué: {tid}')
        seen.add(tid)

        if tid and (f'/status/{tid}' not in url):
            errors.append(f'[{i}] url ne contient pas /status/<tweet_id>: {url}')

        if status not in VALID_STATUS:
            errors.append(f'[{i}] status invalide: {status!r} (attendu: {sorted(VALID_STATUS)})')

    if errors:
        print('Manifest invalide:')
        for e in errors:
            print('-', e)
        return 1

    print(f'OK: manifest valide ({len(items)} items, {len(seen)} IDs uniques)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
