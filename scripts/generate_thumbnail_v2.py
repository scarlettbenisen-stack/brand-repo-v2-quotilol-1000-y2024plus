#!/usr/bin/env python3
import json
import re
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / 'analysis'
REPORT_PATH = ANALYSIS / 'extracted_brand_full_report.json'
VISUAL_TAGS_PATH = ANALYSIS / 'visual_tags.json'
OUT_DIR = ROOT / 'previews_v2'
MAP_PATH = ANALYSIS / 'thumb_v2_map.json'

MAX_SIDE = 320
WEBP_QUALITY = 80
SHARPEN_AMOUNT = 1.12
CONTRAST_AMOUNT = 1.05
ALLOWED = {'.jpg', '.jpeg', '.png', '.webp'}


def tweet_id_from_file(name: str):
    m = re.search(r'tweet_(\d+)', name)
    return m.group(1) if m else None


def image_dims(path: Path):
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


def select_best_image(files):
    best = None
    best_score = -1
    for f in files:
        p = Path(f)
        if p.suffix.lower() not in ALLOWED or not p.exists():
            continue
        dims = image_dims(p)
        if not dims:
            continue
        w, h = dims
        score = w * h
        if score > best_score:
            best_score = score
            best = (p, w, h)
    return best


def make_thumb(src: Path, out: Path):
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ('RGB', 'RGBA'):
            im = im.convert('RGB')
        # light enhancement
        im = ImageEnhance.Contrast(im).enhance(CONTRAST_AMOUNT)
        im = im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=2))

        w, h = im.size
        scale = min(MAX_SIDE / max(w, h), 1.0)
        nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        if (nw, nh) != (w, h):
            im = im.resize((nw, nh), Image.Resampling.LANCZOS)

        if im.mode == 'RGBA':
            im.save(out, 'WEBP', quality=WEBP_QUALITY, method=6)
        else:
            im.convert('RGB').save(out, 'WEBP', quality=WEBP_QUALITY, method=6)
        return nw, nh


def main():
    OUT_DIR.mkdir(exist_ok=True)

    report = json.loads(REPORT_PATH.read_text())
    visual = json.loads(VISUAL_TAGS_PATH.read_text())

    mapping = {}
    for row in report.get('items', []):
        tid = row.get('tweet_id')
        best = select_best_image(row.get('files') or [])
        if best:
            p, w, h = best
            mapping[tid] = {
                'source': str(p.relative_to(ROOT)),
                'source_abs': str(p),
                'source_w': w,
                'source_h': h,
                'source_area': w * h,
            }

    upgraded = 0
    missing = 0
    errors = 0

    for it in visual.get('items', []):
        if it.get('class') != 'brand_visual':
            continue
        tid = tweet_id_from_file(it.get('file', ''))
        if not tid or tid not in mapping:
            missing += 1
            continue
        src = Path(mapping[tid]['source_abs'])
        out_name = f"tweet_{tid}.webp"
        out_path = OUT_DIR / out_name
        try:
            tw, th = make_thumb(src, out_path)
            it['thumb_v2'] = f"./previews_v2/{out_name}"
            mapping[tid]['thumb_v2'] = f"previews_v2/{out_name}"
            mapping[tid]['thumb_w'] = tw
            mapping[tid]['thumb_h'] = th
            mapping[tid]['thumb_bytes'] = out_path.stat().st_size
            upgraded += 1
        except Exception:
            errors += 1

    visual['thumb_v2_meta'] = {
        'max_side': MAX_SIDE,
        'format': 'webp',
        'quality': WEBP_QUALITY,
        'contrast': CONTRAST_AMOUNT,
        'unsharp_mask': {'radius': 1.2, 'percent': 110, 'threshold': 2},
    }

    VISUAL_TAGS_PATH.write_text(json.dumps(visual, ensure_ascii=False, indent=2) + '\n')
    MAP_PATH.write_text(json.dumps({
        'generated_at': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
        'max_side': MAX_SIDE,
        'quality': WEBP_QUALITY,
        'items': mapping,
        'stats': {
            'mapping_count': len(mapping),
            'brand_upgraded': upgraded,
            'missing_mapping': missing,
            'errors': errors,
        }
    }, ensure_ascii=False, indent=2) + '\n')

    print(json.dumps({'mapping_count': len(mapping), 'brand_upgraded': upgraded, 'missing': missing, 'errors': errors}))


if __name__ == '__main__':
    main()
