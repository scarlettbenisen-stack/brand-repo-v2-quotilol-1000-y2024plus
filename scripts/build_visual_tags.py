#!/usr/bin/env python3
import json
import colorsys
from pathlib import Path

import numpy as np
from PIL import Image

BASE = Path(__file__).resolve().parents[1]
CLEAN = BASE / 'clean'
ANALYSIS = BASE / 'analysis'
ANALYSIS.mkdir(parents=True, exist_ok=True)

CLASS_FILE = ANALYSIS / 'brand_classification_3classes.json'
OUT = ANALYSIS / 'visual_tags.json'


def edge_density(gray):
    gx = np.abs(np.diff(gray, axis=1))
    gy = np.abs(np.diff(gray, axis=0))
    g = np.pad(gx, ((0, 0), (0, 1)), mode='constant') + np.pad(gy, ((0, 1), (0, 0)), mode='constant')
    thr = np.percentile(g, 82)
    return float((g > thr).mean())


def colorfulness(rgb):
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    rg = np.abs(r - g)
    yb = np.abs(0.5 * (r + g) - b)
    return float(np.sqrt(np.std(rg) ** 2 + np.std(yb) ** 2) + 0.3 * np.sqrt(np.mean(rg) ** 2 + np.mean(yb) ** 2))


def rgb_to_hsv_stats(rgb):
    arr = (rgb / 255.0).reshape(-1, 3)
    hsv = np.array([colorsys.rgb_to_hsv(*px) for px in arr])
    h, s, v = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    return float(np.mean(h)), float(np.mean(s)), float(np.mean(v)), float(np.std(s)), float(np.std(v))


def dominant_color_bucket(mean_h, mean_s):
    if mean_s < 0.12:
        return 'gray'
    deg = mean_h * 360
    if deg < 20 or deg >= 345:
        return 'red'
    if deg < 45:
        return 'orange'
    if deg < 70:
        return 'yellow'
    if deg < 150:
        return 'green'
    if deg < 200:
        return 'cyan'
    if deg < 255:
        return 'blue'
    if deg < 300:
        return 'purple'
    return 'pink'


def palette_temperature(mean_h, mean_s):
    if mean_s < 0.12:
        return 'neutral'
    deg = mean_h * 360
    if (deg < 70) or (deg >= 300):
        return 'warm'
    if 160 <= deg < 280:
        return 'cool'
    return 'neutral'


def level_from_value(v, cuts, labels):
    for cut, label in zip(cuts, labels):
        if v <= cut:
            return label
    return labels[-1]


def analyze(path: Path):
    img = Image.open(path).convert('RGB')
    img.thumbnail((768, 768))
    rgb = np.asarray(img).astype(np.float32)
    gray = np.dot(rgb[..., :3], [0.299, 0.587, 0.114])

    ed = edge_density(gray)
    cf = colorfulness(rgb)
    mean_h, mean_s, mean_v, std_s, std_v = rgb_to_hsv_stats(rgb)

    mono = bool(mean_s < 0.10 and std_s < 0.08)
    saturation_level = level_from_value(mean_s, [0.18, 0.42], ['muted', 'balanced', 'vivid'])
    contrast_level = level_from_value(float(np.std(gray)), [22, 42], ['low', 'medium', 'high'])
    brightness_level = level_from_value(mean_v, [0.35, 0.68], ['dark', 'mid', 'bright'])
    composition_density = level_from_value(ed, [0.16, 0.28], ['airy', 'balanced', 'dense'])

    negative_space = 'high' if composition_density == 'airy' else ('low' if composition_density == 'dense' else 'medium')

    # lightweight branding-oriented proxies
    visual_mode = 'type_logo_likely' if (mono and ed > 0.18) or (contrast_level == 'high' and saturation_level == 'muted') else (
        'photo_likely' if cf > 95 and saturation_level == 'vivid' else 'mixed'
    )

    return {
        'file': path.name,
        'dominant_color': dominant_color_bucket(mean_h, mean_s),
        'palette_temperature': palette_temperature(mean_h, mean_s),
        'monochrome': mono,
        'saturation_level': saturation_level,
        'contrast_level': contrast_level,
        'brightness_level': brightness_level,
        'composition_density': composition_density,
        'negative_space': negative_space,
        'visual_mode': visual_mode,
        'metrics': {
            'edge_density': round(ed, 4),
            'colorfulness': round(cf, 2),
            'mean_saturation': round(mean_s, 4),
            'mean_value': round(mean_v, 4)
        }
    }


def main():
    classes = {}
    if CLASS_FILE.exists():
        for row in json.loads(CLASS_FILE.read_text()):
            classes[row['file']] = {'class': row.get('class'), 'confidence': row.get('confidence')}

    items = []
    files = sorted(CLEAN.glob('tweet_*.png'))
    for i, fp in enumerate(files, 1):
        tag = analyze(fp)
        tag.update(classes.get(fp.name, {}))
        items.append(tag)
        if i % 100 == 0:
            print(f'tagged {i}/{len(files)}')

    payload = {
        'version': 1,
        'count': len(items),
        'fields': [
            'class', 'confidence', 'dominant_color', 'palette_temperature', 'monochrome',
            'saturation_level', 'contrast_level', 'brightness_level', 'composition_density',
            'negative_space', 'visual_mode'
        ],
        'items': items
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(f'Wrote {OUT} ({len(items)} items)')


if __name__ == '__main__':
    main()
