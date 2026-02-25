#!/usr/bin/env python3
import csv, json, os, re, time, base64
from pathlib import Path
import requests

BASE = Path(__file__).resolve().parents[1]
CLEAN = BASE / 'clean'
AN = BASE / 'analysis'
REV = BASE / 'review'
AN.mkdir(exist_ok=True, parents=True)
for c in ('brand_visual', 'not_brand', 'uncertain'):
    (REV / c).mkdir(exist_ok=True, parents=True)

OUT_JSON = AN / 'brand_classification_3classes.json'
OUT_CSV = AN / 'brand_classification_3classes.csv'
OUT_SUM = AN / 'brand_classification_summary.md'

MODEL = os.environ.get('OLLAMA_VISION_MODEL', 'moondream')
URL = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434/api/generate')
PROMPT = (
    'Classify this image into exactly one class: brand_visual, not_brand, uncertain. '
    'brand_visual = logo systems, visual identity, branding boards, packaging/brand mockups. '
    'not_brand = memes, selfies, random photos/screenshots, unrelated content. '
    'uncertain = ambiguous/unreadable. '
    'Return ONLY JSON: {"class":"brand_visual|not_brand|uncertain","confidence":0.0,"reason_short":"..."}'
)


def extract_json(text: str):
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def classify(path: Path):
    img_b64 = base64.b64encode(path.read_bytes()).decode('utf-8')
    payload = {
        'model': MODEL,
        'prompt': PROMPT,
        'images': [img_b64],
        'stream': False,
        'options': {'temperature': 0.1}
    }

    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(URL, json=payload, timeout=420)
            r.raise_for_status()
            data = r.json()
            txt = data.get('response', '')
            obj = extract_json(txt) or {}
            c = obj.get('class', 'uncertain')
            if c not in ('brand_visual', 'not_brand', 'uncertain'):
                c = 'uncertain'
            try:
                conf = float(obj.get('confidence', 0.5))
            except Exception:
                conf = 0.5
            conf = max(0.0, min(1.0, conf))
            reason = str(obj.get('reason_short', ''))[:180] or 'ok'
            return c, conf, reason
        except Exception as e:
            last_err = str(e)
            time.sleep(1.5 * (attempt + 1))

    return 'uncertain', 0.05, f'ollama_error: {last_err[:130] if last_err else "unknown"}'


files = sorted(CLEAN.glob('tweet_*.png'))
records = []

for i, fp in enumerate(files, 1):
    c, conf, reason = classify(fp)
    records.append({'file': fp.name, 'class': c, 'confidence': conf, 'reason_short': reason})
    if i % 20 == 0:
        OUT_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
        print(f'done {i}/{len(files)}')

OUT_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')

with OUT_CSV.open('w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['file', 'class', 'confidence', 'reason_short'])
    w.writeheader()
    w.writerows(records)

# refresh symlinks
for cls in ('brand_visual', 'not_brand', 'uncertain'):
    d = REV / cls
    for x in d.iterdir():
        try:
            x.unlink()
        except Exception:
            pass

counts = {'brand_visual': 0, 'not_brand': 0, 'uncertain': 0}
for r in records:
    cls = r['class'] if r['class'] in counts else 'uncertain'
    counts[cls] += 1
    src = CLEAN / r['file']
    dst = REV / cls / r['file']
    try:
        dst.symlink_to(src)
    except Exception:
        pass

buckets = {'high': 0, 'medium': 0, 'low': 0}
for r in records:
    c = float(r['confidence'])
    if c >= 0.8:
        buckets['high'] += 1
    elif c >= 0.5:
        buckets['medium'] += 1
    else:
        buckets['low'] += 1

uncertain = [r for r in records if r['class'] == 'uncertain']
md = [
    '# Brand classification summary (Ollama local)',
    '',
    f'- Model: `{MODEL}`',
    f'- Total: **{len(records)}**',
    f"- brand_visual: **{counts['brand_visual']}**",
    f"- not_brand: **{counts['not_brand']}**",
    f"- uncertain: **{counts['uncertain']}**",
    '',
    '## Confidence buckets',
    f"- high (>=0.8): {buckets['high']}",
    f"- medium (0.5-0.79): {buckets['medium']}",
    f"- low (<0.5): {buckets['low']}",
    '',
    '## Uncertain list',
]
for r in uncertain:
    md.append(f"- {r['file']} | conf={r['confidence']:.2f} | {r['reason_short']}")
OUT_SUM.write_text('\n'.join(md) + '\n', encoding='utf-8')

print('DONE', counts, buckets)
