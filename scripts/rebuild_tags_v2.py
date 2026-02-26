#!/usr/bin/env python3
import json
import math
import random
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

BASE = Path(__file__).resolve().parents[1]
ANALYSIS = BASE / 'analysis'
INPUT_JSON = ANALYSIS / 'visual_tags.json'
OUT_JSON = ANALYSIS / 'visual_tags.json'
OUT_REPORT = ANALYSIS / 'tagging_v2_report.md'
PREVIEWS_V2 = BASE / 'previews_v2'
CLEAN = BASE / 'clean'

COLOR_LABELS = ['gray', 'red', 'orange', 'yellow', 'green', 'cyan', 'blue', 'purple', 'pink']
TYPO_LABELS = ['serif', 'sans', 'mixed', 'display', 'unknown']


def load_rgb(path: Path, max_side: int = 768) -> np.ndarray:
    img = Image.open(path).convert('RGB')
    img.thumbnail((max_side, max_side))
    return np.asarray(img).astype(np.float32)


def rgb_to_hsv_arr(rgb01: np.ndarray) -> np.ndarray:
    # rgb01: [N,3], values in [0,1]
    r = rgb01[:, 0]
    g = rgb01[:, 1]
    b = rgb01[:, 2]

    cmax = np.max(rgb01, axis=1)
    cmin = np.min(rgb01, axis=1)
    delta = cmax - cmin

    h = np.zeros_like(cmax)
    mask = delta > 1e-8

    rr = (cmax == r) & mask
    gg = (cmax == g) & mask
    bb = (cmax == b) & mask

    h[rr] = np.mod((g[rr] - b[rr]) / delta[rr], 6.0)
    h[gg] = ((b[gg] - r[gg]) / delta[gg]) + 2.0
    h[bb] = ((r[bb] - g[bb]) / delta[bb]) + 4.0
    h = (h / 6.0) % 1.0

    s = np.zeros_like(cmax)
    nz = cmax > 1e-8
    s[nz] = delta[nz] / cmax[nz]

    v = cmax
    return np.stack([h, s, v], axis=1)


def hue_bucket(h_deg: float) -> str:
    if h_deg < 20 or h_deg >= 345:
        return 'red'
    if h_deg < 45:
        return 'orange'
    if h_deg < 70:
        return 'yellow'
    if h_deg < 150:
        return 'green'
    if h_deg < 200:
        return 'cyan'
    if h_deg < 255:
        return 'blue'
    if h_deg < 300:
        return 'purple'
    return 'pink'


def choose_source_image(file_name: str) -> Path:
    preview = PREVIEWS_V2 / file_name.replace('.png', '.webp')
    clean = CLEAN / file_name

    if preview.exists():
        try:
            p_rgb = load_rgb(preview, max_side=512)
            h, w = p_rgb.shape[:2]
            gray = np.dot(p_rgb[..., :3], [0.299, 0.587, 0.114])
            variance = float(np.std(gray))
            # "Enough info": decent size + non-flat luminance.
            if min(h, w) >= 180 and variance >= 8.0:
                return preview
        except Exception:
            pass

    return clean if clean.exists() else preview


def analyze_color_v2(rgb: np.ndarray, seed: int = 0):
    arr = (rgb / 255.0).reshape(-1, 3)
    if arr.shape[0] == 0:
        return {
            'dominant_color_v2': 'gray',
            'top2_colors_v2': ['gray'],
            'palette_temperature_v2': 'neutral',
            'dominant_ratio_v2': 0.0,
        }

    rnd = np.random.default_rng(seed)
    if arr.shape[0] > 18000:
        idx = rnd.choice(arr.shape[0], size=18000, replace=False)
        arr = arr[idx]

    hsv = rgb_to_hsv_arr(arr)
    h = hsv[:, 0]
    s = hsv[:, 1]
    v = hsv[:, 2]

    non_extreme = (v > 0.06) & (v < 0.96)
    colorful = non_extreme & (s > 0.12)

    # If image is near monochrome, keep neutral output.
    if colorful.sum() < 160:
        return {
            'dominant_color_v2': 'gray',
            'top2_colors_v2': ['gray'],
            'palette_temperature_v2': 'neutral',
            'dominant_ratio_v2': round(float(colorful.sum() / max(len(arr), 1)), 4),
        }

    hh = h[colorful]
    ss = s[colorful]
    vv = v[colorful]

    # Weighted hue voting (saturation + luminance confidence), robust against washed backgrounds.
    weights = (0.5 + 0.5 * ss) * (0.35 + 0.65 * vv)
    bucket_scores = Counter()
    for hd, wgt in zip(hh * 360.0, weights):
        bucket_scores[hue_bucket(float(hd))] += float(wgt)

    ranked = [name for name, _ in bucket_scores.most_common()]
    if not ranked:
        ranked = ['gray']

    dominant = ranked[0]
    top2 = ranked[:2]
    total_score = sum(bucket_scores.values())
    dominant_ratio = (bucket_scores[dominant] / total_score) if total_score > 0 else 0.0

    warm = sum(bucket_scores[c] for c in ('red', 'orange', 'yellow', 'pink'))
    cool = sum(bucket_scores[c] for c in ('green', 'cyan', 'blue', 'purple'))

    if abs(warm - cool) / max(total_score, 1e-8) < 0.16:
        temp = 'neutral'
    else:
        temp = 'warm' if warm > cool else 'cool'

    return {
        'dominant_color_v2': dominant,
        'top2_colors_v2': top2,
        'palette_temperature_v2': temp,
        'dominant_ratio_v2': round(float(np.clip(dominant_ratio, 0.0, 1.0)), 4),
    }


def analyze_typography_v2(rgb: np.ndarray):
    gray = np.dot(rgb[..., :3], [0.299, 0.587, 0.114])

    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, :-1] = np.diff(gray, axis=1)
    gy[:-1, :] = np.diff(gray, axis=0)

    mag = np.hypot(gx, gy)
    p88 = np.percentile(mag, 88)
    edge_mask = mag >= p88
    edge_density = float(edge_mask.mean())

    if edge_density < 0.03:
        return {
            'typo_primary_v2': 'unknown',
            'typo_case_v2': 'unknown',
            'typo_confidence_v2': 0.2,
        }

    # Orientation buckets on edge pixels.
    ang = np.arctan2(np.abs(gy[edge_mask]), np.abs(gx[edge_mask]) + 1e-8)
    h_ratio = float((ang < math.pi / 8).mean())
    v_ratio = float((ang > 3 * math.pi / 8).mean())
    d_ratio = float(1.0 - h_ratio - v_ratio)

    contrast = float(np.std(gray))

    serif_score = 0.52 * h_ratio + 0.32 * d_ratio + 0.16 * min(contrast / 64.0, 1.0)
    sans_score = 0.56 * max(0.0, 1.0 - d_ratio) + 0.24 * (1.0 - abs(h_ratio - v_ratio)) + 0.20 * min(contrast / 64.0, 1.0)
    display_score = 0.58 * d_ratio + 0.22 * min(contrast / 64.0, 1.0) + 0.20 * min(edge_density / 0.18, 1.0)

    scores = {
        'serif': serif_score,
        'sans': sans_score,
        'display': display_score,
    }

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_label, best_score = ordered[0]
    second_score = ordered[1][1]

    margin = abs(best_score - second_score)
    if best_score < 0.50:
        primary = 'unknown'
    elif margin < 0.05:
        primary = 'mixed'
    elif margin < 0.11:
        primary = 'unknown'
    else:
        primary = best_label

    # Case proxy (very heuristic): edge row concentration + orientation balance.
    row_energy = mag.mean(axis=1)
    if row_energy.max() > 0:
        active_rows = row_energy > (0.42 * row_energy.max())
        active_span = float(active_rows.sum() / len(active_rows))
    else:
        active_span = 0.0

    if primary == 'unknown':
        case = 'unknown'
        case_conf = 0.0
    elif active_span < 0.30 and v_ratio >= h_ratio * 0.9:
        case = 'upper'
        case_conf = 0.56
    elif active_span > 0.58 and h_ratio > v_ratio:
        case = 'lower'
        case_conf = 0.52
    elif 0.30 <= active_span <= 0.58:
        case = 'mixed'
        case_conf = 0.5
    else:
        case = 'unknown'
        case_conf = 0.35

    conf = np.clip(0.35 + 0.75 * max(0.0, best_score - second_score) + 0.12 * case_conf, 0.0, 1.0)

    return {
        'typo_primary_v2': primary,
        'typo_case_v2': case,
        'typo_confidence_v2': round(float(conf), 4),
    }


def rebuild_v2():
    payload = json.loads(INPUT_JSON.read_text())
    items = payload.get('items', [])

    dom_counter = Counter()
    typo_counter = Counter()

    for i, item in enumerate(items, 1):
        file_name = item['file']
        src = choose_source_image(file_name)
        if not src.exists():
            # Preserve prior item and mark unknowns if file is unavailable.
            item.update({
                'dominant_color_v2': item.get('dominant_color', 'gray'),
                'top2_colors_v2': [item.get('dominant_color', 'gray')],
                'palette_temperature_v2': item.get('palette_temperature', 'neutral'),
                'dominant_ratio_v2': 0.0,
                'typo_primary_v2': 'unknown',
                'typo_case_v2': 'unknown',
                'typo_confidence_v2': 0.0,
            })
            continue

        rgb = load_rgb(src)
        seed = abs(hash(file_name)) % (2**32)
        color_tags = analyze_color_v2(rgb, seed=seed)
        typo_tags = analyze_typography_v2(rgb)

        item.update(color_tags)
        item.update(typo_tags)

        dom_counter[item['dominant_color_v2']] += 1
        typo_counter[item['typo_primary_v2']] += 1

        if i % 100 == 0:
            print(f'processed {i}/{len(items)}')

    # Keep existing fields and append v2 fields metadata.
    fields = payload.get('fields', [])
    for f in [
        'dominant_color_v2', 'top2_colors_v2', 'palette_temperature_v2', 'dominant_ratio_v2',
        'typo_primary_v2', 'typo_case_v2', 'typo_confidence_v2'
    ]:
        if f not in fields:
            fields.append(f)
    payload['fields'] = fields
    payload['version'] = max(int(payload.get('version', 1)), 2)
    payload['count'] = len(items)

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')

    return payload, dom_counter, typo_counter


def write_report(total: int, dom_counter: Counter, typo_counter: Counter):
    def render_counter(counter: Counter, labels):
        lines = []
        for k in labels:
            v = counter.get(k, 0)
            pct = (100.0 * v / total) if total else 0.0
            lines.append(f'- **{k}**: {v} ({pct:.1f}%)')
        extra = [k for k in counter.keys() if k not in labels]
        for k in sorted(extra):
            v = counter[k]
            pct = (100.0 * v / total) if total else 0.0
            lines.append(f'- **{k}**: {v} ({pct:.1f}%)')
        return '\n'.join(lines)

    report = f"""# Tagging V2 Report

- Dataset size: **{total}** items
- Generated by: `scripts/rebuild_tags_v2.py`

## dominant_color_v2 distribution
{render_counter(dom_counter, COLOR_LABELS)}

## typo_primary_v2 distribution
{render_counter(typo_counter, TYPO_LABELS)}

## Caveats
- Typography tags are **CV proxy heuristics**, not OCR/font-recognition ground truth.
- Small or highly stylized visuals can collapse to `unknown`/`mixed` by design.
- Color extraction ignores very dark/very bright and low-saturation pixels to reduce background bias.
- `previews_v2/` is used when sufficiently informative (size + luminance variance), otherwise `clean/` is used.
"""
    OUT_REPORT.write_text(report)


def main():
    payload, dom_counter, typo_counter = rebuild_v2()
    total = len(payload.get('items', []))
    write_report(total, dom_counter, typo_counter)
    print(f'Wrote {OUT_JSON} with {total} items')
    print(f'Wrote {OUT_REPORT}')


if __name__ == '__main__':
    main()
