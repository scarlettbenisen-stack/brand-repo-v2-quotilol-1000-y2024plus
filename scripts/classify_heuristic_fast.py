#!/usr/bin/env python3
import csv, json, math
from pathlib import Path
from PIL import Image
import numpy as np

BASE = Path(__file__).resolve().parents[1]
CLEAN = BASE / 'clean'
AN = BASE / 'analysis'
REV = BASE / 'review'
AN.mkdir(parents=True, exist_ok=True)
for c in ('brand_visual','not_brand','uncertain'):
    (REV / c).mkdir(parents=True, exist_ok=True)

OUT_JSON = AN / 'brand_classification_3classes.json'
OUT_CSV = AN / 'brand_classification_3classes.csv'
OUT_SUM = AN / 'brand_classification_summary.md'


def colorfulness(rgb):
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    rg = np.abs(r - g)
    yb = np.abs(0.5 * (r + g) - b)
    std_rg, std_yb = np.std(rg), np.std(yb)
    mean_rg, mean_yb = np.mean(rg), np.mean(yb)
    return math.sqrt(std_rg**2 + std_yb**2) + 0.3 * math.sqrt(mean_rg**2 + mean_yb**2)


def edge_density(gray):
    gx = np.abs(np.diff(gray, axis=1))
    gy = np.abs(np.diff(gray, axis=0))
    g = np.pad(gx, ((0,0),(0,1)), mode='constant') + np.pad(gy, ((0,1),(0,0)), mode='constant')
    thr = np.percentile(g, 80)
    return float((g > thr).mean()), float(g.mean())


def white_ratio(rgb):
    m = (rgb[:,:,0] > 220) & (rgb[:,:,1] > 220) & (rgb[:,:,2] > 220)
    return float(m.mean())


def dark_ratio(rgb):
    m = (rgb[:,:,0] < 40) & (rgb[:,:,1] < 40) & (rgb[:,:,2] < 40)
    return float(m.mean())


def classify(img_path):
    img = Image.open(img_path).convert('RGB')
    img.thumbnail((768, 768))
    arr = np.asarray(img).astype(np.float32)
    gray = np.dot(arr[..., :3], [0.299, 0.587, 0.114])

    cf = colorfulness(arr)
    ed, gmean = edge_density(gray)
    wr = white_ratio(arr)
    dr = dark_ratio(arr)
    std = float(gray.std())

    # Heuristic rules tuned for review-first sorting
    # brand_visual probable: structured design boards, logos, typography layouts
    if ((wr > 0.35 and ed > 0.18 and std > 28) or
        (cf < 55 and ed > 0.2 and 12 < dr < 0.65) or
        (25 < cf < 85 and ed > 0.24 and std > 24)):
        return 'brand_visual', 0.66, f'layout-like cf={cf:.1f} ed={ed:.2f} std={std:.1f}'

    # not brand probable: photo-like/noisy scenes or very flat random content
    if ((cf > 95 and ed < 0.2) or
        (cf > 110 and std < 30) or
        (ed < 0.14 and std < 22) or
        (dr > 0.82 or wr > 0.92)):
        return 'not_brand', 0.63, f'photo/flat cf={cf:.1f} ed={ed:.2f} std={std:.1f}'

    return 'uncertain', 0.45, f'ambiguous cf={cf:.1f} ed={ed:.2f} std={std:.1f}'


files = sorted(CLEAN.glob('tweet_*.png'))
records = []
for i, fp in enumerate(files, 1):
    c, conf, rs = classify(fp)
    records.append({'file': fp.name, 'class': c, 'confidence': conf, 'reason_short': rs})
    if i % 100 == 0:
        print(f'done {i}/{len(files)}')

OUT_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
with OUT_CSV.open('w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['file','class','confidence','reason_short'])
    w.writeheader(); w.writerows(records)

# refresh review symlinks
for cls in ('brand_visual','not_brand','uncertain'):
    d = REV / cls
    for x in d.iterdir():
        try:
            x.unlink()
        except Exception:
            pass

counts = {'brand_visual':0,'not_brand':0,'uncertain':0}
for r in records:
    cls = r['class']
    counts[cls] += 1
    src = CLEAN / r['file']
    dst = REV / cls / r['file']
    try:
        dst.symlink_to(src)
    except Exception:
        pass

md = []
md.append('# Brand classification summary (heuristic local)')
md.append('')
md.append(f'- Total: **{len(records)}**')
md.append(f"- brand_visual: **{counts['brand_visual']}**")
md.append(f"- not_brand: **{counts['not_brand']}**")
md.append(f"- uncertain: **{counts['uncertain']}**")
md.append('')
md.append('## Notes')
md.append('- This pass is heuristic-only for fast review triage.')
md.append('- Use uncertain bucket for manual check first.')
OUT_SUM.write_text('\n'.join(md) + '\n', encoding='utf-8')

print('DONE', counts)
