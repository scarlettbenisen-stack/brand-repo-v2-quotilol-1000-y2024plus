#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "input/new_urls_2026-10-13.txt"
META_ITEMS = ROOT / "meta/items.json"
MANIFEST = ROOT / "manifest.json"
EXTRACT_REPORT = ROOT / "analysis/extracted_brand_full_report.json"
VISUAL_TAGS = ROOT / "analysis/visual_tags.json"
LINKS_FILE = ROOT / "analysis/brand_twitter_links.txt"
OUT_DIR = ROOT / "analysis/extracted_brand_full"
CLEAN = ROOT / "clean"
PREVIEWS = ROOT / "previews_v2"
REPORT = ROOT / "analysis/import_2026-10-13_report.json"

USER_AGENT = "Mozilla/5.0 (compatible; brand-repo-import/1.0)"
MAX_SIDE = 320
WEBP_QUALITY = 80


def read_json(path: Path, default: Any):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_tweet_id(url: str):
    m = re.search(r"/(?:status|statuses)/(\d+)", url)
    return m.group(1) if m else None


def parse_input():
    rows = []
    for line in INPUT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url, _, comment = line.partition("#")
        url = url.strip()
        tid = extract_tweet_id(url)
        if not tid:
            continue
        rows.append({"tweet_id": tid, "url": url, "comment": comment.strip()})
    return rows


def http_json(url: str, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except HTTPError as e:
            last = e
            if e.code == 404:
                break
        except Exception as e:
            last = e
        time.sleep(1.2 * (attempt + 1))
    raise last or RuntimeError("JSON fetch failed")


def http_bytes(url: str, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception as e:
            last = e
        time.sleep(1.0 * (attempt + 1))
    raise last or RuntimeError("download failed")


def ext_from_url(url: str):
    parsed = urlparse(url)
    path = parsed.path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov"):
        if path.endswith(ext):
            return ext
    q = parse_qs(parsed.query)
    fmt = (q.get("format") or [""])[0].lower()
    if fmt in {"jpg", "jpeg", "png", "webp", "gif"}:
        return "." + fmt
    if "video" in parsed.netloc or "video" in path:
        return ".mp4"
    return ".bin"


def collect_media_urls(obj: Any):
    urls = []

    def add(value):
        if isinstance(value, str) and value.startswith("http"):
            low = value.lower()
            if any(token in low for token in ("pbs.twimg.com", "video.twimg.com", ".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov")):
                urls.append(value)

    def walk(value):
        if isinstance(value, dict):
            for key in ("url", "thumbnail_url", "thumbnailUrl", "poster", "src"):
                add(value.get(key))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(obj)
    seen = set()
    out = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def image_area(path: Path):
    try:
        with Image.open(path) as im:
            w, h = im.size
            return w * h
    except Exception:
        return -1


def save_clean_png(src: Path, dest: Path):
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        if im.mode == "RGBA":
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        im.convert("RGB").save(dest, "PNG", optimize=True)


def make_preview(src: Path, dest: Path):
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im = ImageEnhance.Contrast(im).enhance(1.05)
        im = im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=2))
        w, h = im.size
        scale = min(MAX_SIDE / max(w, h), 1.0)
        if scale < 1.0:
            im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)
        im.save(dest, "WEBP", quality=WEBP_QUALITY, method=6)


def analyze_visual(clean_path: Path, author: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_visual_tags
    import rebuild_tags_v2
    import rebuild_typo_v3_full

    item = build_visual_tags.analyze(clean_path)
    item.update({
        "class": "brand_visual",
        "confidence": 0.99,
        "thumb_v2": f"./previews_v2/{clean_path.stem}.webp",
        "author_handle": author or "unknown",
    })
    rgb = rebuild_tags_v2.load_rgb(PREVIEWS / f"{clean_path.stem}.webp", max_side=512)
    item.update(rebuild_tags_v2.analyze_color_v2(rgb, seed=int(re.search(r"\d+", clean_path.stem).group(0)) % 100000))
    item.update(rebuild_tags_v2.analyze_typography_v2(rgb))
    gray = rebuild_typo_v3_full.safe_read_gray(clean_path)
    typo_v3 = rebuild_typo_v3_full.infer_typo_v3(gray) if gray is not None else {
        "typo_present_v3": False,
        "typo_primary_v3": "no_typo",
        "typo_case_v3": "na",
        "typo_confidence_v3": 0.15,
    }
    typo_v3.pop("_debug", None)
    item.update(typo_v3)
    return item


def update_or_append(items: list[dict], key: str, value: str, row: dict):
    for idx, item in enumerate(items):
        if str(item.get(key)) == value:
            items[idx] = row
            return
    items.append(row)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CLEAN.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)

    rows = parse_input()
    meta = read_json(META_ITEMS, {"items": []})
    manifest = read_json(MANIFEST, {"items": []})
    extracted = read_json(EXTRACT_REPORT, {"items": []})
    visual = read_json(VISUAL_TAGS, {"version": 1, "items": [], "fields": []})

    existing_visual = {str(it.get("file")) for it in visual.get("items", [])}
    visual_items = [it for it in visual.get("items", []) if str(it.get("file")) not in {f"tweet_{r['tweet_id']}.png" for r in rows}]

    added = []
    failed = []
    skipped_existing = []

    for index, row in enumerate(rows, 1):
        tid = row["tweet_id"]
        file_name = f"tweet_{tid}.png"
        clean_path = CLEAN / file_name
        preview_path = PREVIEWS / f"tweet_{tid}.webp"
        print(f"[{index}/{len(rows)}] {tid}", flush=True)

        try:
            payload = http_json(f"https://api.fxtwitter.com/status/{tid}")
            tweet = payload.get("tweet") or {}
            if not tweet:
                raise RuntimeError(payload.get("message") or "missing tweet payload")
            media_urls = collect_media_urls(tweet.get("media") or tweet)
            if not media_urls:
                raise RuntimeError("no media URLs found")

            saved = []
            image_files = []
            for n, media_url in enumerate(media_urls, 1):
                ext = ext_from_url(media_url)
                out_path = OUT_DIR / f"tweet_{tid}_{n}{ext}"
                if not out_path.exists() or out_path.stat().st_size == 0:
                    out_path.write_bytes(http_bytes(media_url))
                saved.append(str(out_path))
                if ext.lower() in {".jpg", ".jpeg", ".png", ".webp"} and image_area(out_path) > 0:
                    image_files.append(out_path)

            if not image_files:
                raise RuntimeError("no downloadable image media found")

            best = max(image_files, key=image_area)
            save_clean_png(best, clean_path)
            make_preview(clean_path, preview_path)

            author = ((tweet.get("author") or {}).get("screen_name") or urlparse(row["url"]).path.split("/")[1] or "unknown")
            text = (tweet.get("text") or row.get("comment") or "").strip()
            canonical_url = tweet.get("url") or f"https://x.com/i/web/status/{tid}"

            update_or_append(meta["items"], "tweet_id", tid, {
                "tweet_id": tid,
                "url": canonical_url,
                "image": f"previews_v2/tweet_{tid}.webp",
                "text": text,
                "status": "ok",
                "author_handle": author,
                "created_at": tweet.get("created_at"),
            })
            update_or_append(manifest["items"], "tweet_id", tid, {
                "tweet_id": tid,
                "url": canonical_url,
                "status": "ok",
                "files": saved,
                "error": None,
                "author_handle": author,
            })
            update_or_append(extracted["items"], "tweet_id", tid, {
                "tweet_id": tid,
                "url": canonical_url,
                "status": "ok",
                "files": saved,
                "error": None,
                "author_handle": author,
            })
            visual_items.append(analyze_visual(clean_path, author))

            if file_name in existing_visual:
                skipped_existing.append(canonical_url)
            else:
                added.append(canonical_url)

        except Exception as exc:
            failed.append({"tweet_id": tid, "url": row["url"], "error": str(exc)})
            update_or_append(meta["items"], "tweet_id", tid, {
                "tweet_id": tid,
                "url": row["url"],
                "image": f"previews_v2/tweet_{tid}.webp",
                "text": row.get("comment", ""),
                "status": "failed",
                "error": str(exc),
            })

    def sort_key(item):
        try:
            return int(item.get("tweet_id") or re.search(r"tweet_(\d+)", item.get("file", "")).group(1))
        except Exception:
            return 0

    meta["items"].sort(key=sort_key, reverse=True)
    manifest["items"].sort(key=sort_key, reverse=True)
    extracted["items"].sort(key=sort_key, reverse=True)
    visual_items.sort(key=sort_key, reverse=True)

    meta_ok = sum(1 for x in meta["items"] if x.get("status") == "ok")
    manifest["total_tweets"] = len(manifest["items"])
    manifest["ok_tweets"] = sum(1 for x in manifest["items"] if x.get("status") == "ok")
    manifest["failed_tweets"] = sum(1 for x in manifest["items"] if x.get("status") != "ok")
    manifest["total_files"] = sum(len(x.get("files") or []) for x in manifest["items"])
    manifest["status"] = manifest.get("status") or "updated"

    extracted["total_tweets"] = len(extracted["items"])
    extracted["ok_tweets"] = sum(1 for x in extracted["items"] if x.get("status") == "ok")
    extracted["failed_tweets"] = sum(1 for x in extracted["items"] if x.get("status") != "ok")
    extracted["total_files"] = sum(len(x.get("files") or []) for x in extracted["items"])

    visual["items"] = visual_items
    visual["count"] = len(visual_items)
    fields = visual.get("fields") or []
    for field in [
        "class", "confidence", "dominant_color", "palette_temperature", "monochrome",
        "saturation_level", "contrast_level", "brightness_level", "composition_density",
        "negative_space", "visual_mode", "dominant_color_v2", "top2_colors_v2",
        "palette_temperature_v2", "dominant_ratio_v2", "typo_present_v3",
        "typo_primary_v3", "typo_case_v3", "typo_confidence_v3",
    ]:
        if field not in fields:
            fields.append(field)
    visual["fields"] = fields
    visual["version"] = max(int(visual.get("version", 1)), 2)
    visual["thumb_v2_meta"] = {
        "max_side": MAX_SIDE,
        "format": "webp",
        "quality": WEBP_QUALITY,
        "contrast": 1.05,
        "unsharp_mask": {"radius": 1.2, "percent": 110, "threshold": 2},
    }

    write_json(META_ITEMS, meta)
    write_json(MANIFEST, manifest)
    write_json(EXTRACT_REPORT, extracted)
    write_json(VISUAL_TAGS, visual)

    existing_links = set()
    if LINKS_FILE.exists():
        existing_links = {line.strip() for line in LINKS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()}
    with LINKS_FILE.open("a", encoding="utf-8") as f:
        for row in rows:
            canonical = f"https://x.com/i/web/status/{row['tweet_id']}"
            if canonical not in existing_links:
                f.write(canonical + "\n")
                existing_links.add(canonical)

    import_report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_count": len(rows),
        "added_count": len(added),
        "failed_count": len(failed),
        "skipped_existing_count": len(skipped_existing),
        "meta_ok_count": meta_ok,
        "added": added,
        "failed": failed,
        "skipped_existing": skipped_existing,
    }
    write_json(REPORT, import_report)
    print(json.dumps(import_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
