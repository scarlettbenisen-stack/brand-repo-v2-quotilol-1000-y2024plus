#!/usr/bin/env python3
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parents[1]
STATE = BASE / 'auth' / 'x_storage_state.json'
MANIFEST = BASE / 'input' / 'manifest.json'
RAW = BASE / 'raw'; CLEAN = BASE / 'clean'; REJECTED = BASE / 'rejected'; ANALYSIS = BASE / 'analysis'
for d in [RAW, CLEAN, REJECTED, ANALYSIS]: d.mkdir(parents=True, exist_ok=True)

if not STATE.exists():
    raise SystemExit('Missing auth/x_storage_state.json. Run setup_x_session.py first.')
if not MANIFEST.exists():
    raise SystemExit('Missing input/manifest.json')

items = json.loads(MANIFEST.read_text()).get('items', [])
# retry only pending/rejected optional
results=[]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(storage_state=str(STATE), viewport={"width":1600,"height":2200})
    page = ctx.new_page()

    for it in items:
        tid = str(it.get('tweet_id') or '')
        if not tid: continue
        url = f'https://x.com/i/web/status/{tid}'
        row = {'tweet_id': tid, 'url': url, 'status': 'rejected', 'mode': None, 'error': None}
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(1800)
            article = page.locator('article').first
            if article.count() == 0:
                page.screenshot(path=str(REJECTED / f'tweet_{tid}.png'))
                row['mode']='no-article'; results.append(row); continue

            # save raw article
            ab = article.bounding_box()
            if ab:
                page.screenshot(path=str(RAW / f'tweet_{tid}.png'), clip={'x':max(0,ab['x']-12),'y':max(0,ab['y']-12),'width':ab['width']+24,'height':ab['height']+24})

            media = None
            selectors = [
                'article div[data-testid="tweetPhoto"] img',
                'article img[src*="pbs.twimg.com/media"]',
                'article video',
                'article [data-testid="card.wrapper"] img',
            ]
            for sel in selectors:
                loc=page.locator(sel)
                for i in range(min(loc.count(),4)):
                    el=loc.nth(i)
                    try:
                        if not el.is_visible(timeout=200):
                            continue
                        b=el.bounding_box()
                        if b and b['width']*b['height']>50000:
                            media=b; break
                    except Exception:
                        pass
                if media: break

            if media:
                page.screenshot(path=str(CLEAN / f'tweet_{tid}.png'), clip={'x':max(0,media['x']-10),'y':max(0,media['y']-10),'width':media['width']+20,'height':media['height']+20})
                row['status']='ok'; row['mode']='media'
            elif ab:
                page.screenshot(path=str(CLEAN / f'tweet_{tid}.png'), clip={'x':max(0,ab['x']-8),'y':max(0,ab['y']-8),'width':ab['width']+16,'height':ab['height']+16})
                row['status']='ok'; row['mode']='article-fallback'
            else:
                page.screenshot(path=str(REJECTED / f'tweet_{tid}.png'))
                row['mode']='no-bbox'
        except Exception as e:
            row['error']=str(e)
            try: page.screenshot(path=str(REJECTED / f'tweet_{tid}.png'))
            except Exception: pass
        results.append(row)
        print(tid, row['status'], row['mode'])

    ctx.close(); browser.close()

summary={
    'total': len(results),
    'ok': sum(1 for r in results if r['status']=='ok'),
    'rejected': sum(1 for r in results if r['status']!='ok'),
    'media': sum(1 for r in results if r.get('mode')=='media'),
    'article_fallback': sum(1 for r in results if r.get('mode')=='article-fallback'),
    'results': results,
}
(ANALYSIS / 'capture_report_saved_session.json').write_text(json.dumps(summary, indent=2))
print('\nDone', summary)
