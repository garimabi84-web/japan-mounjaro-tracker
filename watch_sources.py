#!/usr/bin/env python3
"""Alert-only clinic source-page change scanner.

No price claims are inferred automatically; a change means a human should re-check
that official page and edit catalog.json and index.html after verification.
"""
from __future__ import annotations
import hashlib
import json
import re
import sys
import datetime as dt
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / 'catalog.json'
STATE = ROOT / 'watch_state.json'
DISPLAY = ROOT / 'monitor.js'
UA = 'MounjaroPriceTracker-SourceChangeChecker/1.0 (personal-research; contact: repo-owner)'


def normalize(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip('/') or '/', '', ''))


def relevant_text(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'noscript', 'svg']):
        tag.decompose()
    text = ' '.join(soup.stripped_strings)
    text = re.sub(r'\s+', ' ', text)
    # Keep context of every price/dosage keyword to reduce noise from large pages.
    ranges = []
    for m in re.finditer(r'(?:マンジャロ|Mounjaro|mounjaro|2[.]5\s*mg|7[.]5\s*mg|10\s*mg|15\s*mg|円|¥|￥)', text, re.I):
        ranges.append((max(m.start()-50, 0), min(m.end()+115, len(text))))
    if not ranges:
        return text[:20000]
    merged = []
    for l, r in ranges:
        if merged and l <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], r))
        else:
            merged.append((l, r))
    return ' '.join(text[l:r] for l, r in merged)[:45000]


def run() -> None:
    cat = json.loads(CATALOG.read_text(encoding='utf-8'))
    old = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    seen = set()
    sources = []
    hashes = old.get('hashes', {})
    pending = {} if '--ack' in sys.argv else old.get('pending', {})
    now = dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec='seconds')
    session = requests.Session()
    session.headers.update({'User-Agent': UA, 'Accept-Language': 'ja,ko;q=0.8,en;q=0.7'})
    for clinic in cat['clinics']:
        if clinic.get('status') == 'candidate':
            continue  # candidate URL may be an SNS post; no official price page yet
        url = clinic.get('url', '')
        if not url.startswith('https://'):
            continue
        key = normalize(url)
        if key in seen:
            continue
        seen.add(key)
        names = [x['name'] for x in cat['clinics'] if normalize(x.get('url', '')) == key]
        entry = {'name': names[0], 'url': url, 'status': None}
        try:
            rsp = session.get(url, timeout=(8, 18), allow_redirects=True)
            rsp.raise_for_status()
            text = relevant_text(rsp.text)
            if len(text) < 50:
                raise ValueError('price-page content too short')
            new_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
            prior = hashes.get(key)
            hashes[key] = new_hash
            entry['status'] = 'new' if not prior else ('changed' if prior != new_hash else 'unchanged')
            if entry['status'] == 'changed':
                pending[key] = pending.get(key, {'since': now, 'name': entry['name']})
            elif key in pending:
                entry['status'] = 'changed'
                entry['review_pending_since'] = pending[key]['since']
            entry['text_sample'] = text[:250] if entry['status'] == 'changed' else ''
        except Exception as exc:
            entry['status'] = 'error'
            entry['error'] = str(exc)[:120]
        sources.append(entry)
        print(f"{entry['status']:9} {entry['name'][:24]} {url}")
    STATE.write_text(json.dumps({'ran_at': now, 'hashes': hashes, 'pending': pending}, ensure_ascii=False, indent=2), encoding='utf-8')
    payload = {'ran_at': now, 'sources': sources, 'summary': {
        s: sum(x['status'] == s for x in sources) for s in ['new', 'changed', 'unchanged', 'error']}}
    DISPLAY.write_text('window.__PRICE_WATCH__ = '+json.dumps(payload, ensure_ascii=False, separators=(',', ':'))+';\n', encoding='utf-8')
    print('Result:', json.dumps(payload['summary'], ensure_ascii=False))


if __name__ == '__main__':
    run()
