#!/usr/bin/env python3
import asyncio
import base64
import io
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageStat
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
CLASS_FILE = ROOT / "analysis/brand_classification_3classes.json"
VISUAL_TAGS_FILE = ROOT / "analysis/visual_tags.json"
REPORT_FILE = ROOT / "analysis/hq_pass_report.json"
STORAGE_STATE = ROOT / "auth/x_storage_state.json"
CLEAN_DIR = ROOT / "clean"


def parse_tweet_id(filename: str) -> Optional[str]:
    m = re.match(r"tweet_(\d+)\.png$", filename)
    return m.group(1) if m else None


def img_metrics(path: Path) -> Dict:
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        area = w * h
        gray = rgb.convert("L")
        stat = ImageStat.Stat(gray)
        var = stat.var[0] if stat.var else 0.0
        return {"width": w, "height": h, "area": area, "variance": float(var)}


def bytes_to_metrics_and_png(data: bytes) -> Tuple[Dict, bytes]:
    with Image.open(io.BytesIO(data)) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        area = w * h
        gray = rgb.convert("L")
        stat = ImageStat.Stat(gray)
        var = stat.var[0] if stat.var else 0.0

        out = io.BytesIO()
        rgb.save(out, format="PNG", optimize=True)
        return {"width": w, "height": h, "area": area, "variance": float(var)}, out.getvalue()


def should_replace(old: Dict, new: Dict) -> bool:
    # Prefer clearly larger assets; else modestly better detail.
    if new["area"] >= old["area"] * 1.15:
        return True
    if new["width"] > old["width"] and new["height"] > old["height"]:
        return True
    if new["area"] >= old["area"] * 1.02 and new["variance"] > old["variance"] * 1.25:
        return True
    return False


def build_variants(url: str) -> List[str]:
    out = []
    if "?" in url:
        base, q = url.split("?", 1)
        params = q
        if "name=" in params:
            for n in ["orig", "4096x4096", "large"]:
                out.append(re.sub(r"name=[^&]+", f"name={n}", url))
        else:
            for n in ["orig", "4096x4096", "large"]:
                out.append(f"{url}&name={n}")
    else:
        for n in ["orig", "4096x4096", "large"]:
            out.append(f"{url}?name={n}")
    out.append(url)
    seen = set()
    uniq = []
    for u in out:
        if u not in seen:
            uniq.append(u)
            seen.add(u)
    return uniq


async def fetch_best_media(context, candidates: List[str]) -> Optional[Tuple[bytes, Dict, str]]:
    best = None
    seen = set()
    for src in candidates:
        if "pbs.twimg.com/media" not in src:
            continue
        for u in build_variants(src):
            if u in seen:
                continue
            seen.add(u)
            try:
                r = await context.request.get(u, timeout=15000)
                if not r.ok:
                    continue
                ctype = (r.headers.get("content-type") or "").lower()
                if not ("image/" in ctype):
                    continue
                b = await r.body()
                m, png_bytes = bytes_to_metrics_and_png(b)
                if best is None or m["area"] > best[1]["area"]:
                    best = (png_bytes, m, u)
            except Exception:
                continue
    return best


async def screenshot_lightbox(page) -> Optional[Tuple[bytes, Dict]]:
    click_selectors = [
        '[data-testid="tweetPhoto"] img',
        'article img[src*="pbs.twimg.com/media"]',
    ]
    clicked = False
    for sel in click_selectors:
        el = page.locator(sel).first
        if await el.count() > 0:
            try:
                await el.click(timeout=2000)
                clicked = True
                break
            except Exception:
                pass
    if not clicked:
        return None

    await page.wait_for_timeout(1200)
    box_selectors = [
        '[data-testid="media-modal"]',
        'div[role="dialog"] [aria-label="Image"]',
        'div[role="dialog"]',
    ]
    for sel in box_selectors:
        el = page.locator(sel).first
        if await el.count() > 0:
            try:
                data = await el.screenshot(type="png")
                m, png = bytes_to_metrics_and_png(data)
                return png, m
            except Exception:
                continue
    return None


async def main():
    classes = json.loads(CLASS_FILE.read_text())
    targets = [x["file"] for x in classes if x.get("class") == "brand_visual"]

    processed = 0
    improved = 0
    unchanged = 0
    failed = 0
    improved_samples = []
    failed_samples = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(storage_state=str(STORAGE_STATE), viewport={"width": 1600, "height": 1400})
        page = await context.new_page()

        total = len(targets)
        for file_name in targets:
            processed += 1
            if processed % 25 == 0 or processed == 1:
                print(f"progress {processed}/{total} improved={improved} unchanged={unchanged} failed={failed}", flush=True)
            tweet_id = parse_tweet_id(file_name)
            if not tweet_id:
                failed += 1
                failed_samples.append({"file": file_name, "reason": "bad_filename"})
                continue

            out_path = CLEAN_DIR / file_name
            if not out_path.exists():
                failed += 1
                failed_samples.append({"file": file_name, "reason": "missing_clean_file"})
                continue

            old_m = img_metrics(out_path)
            try:
                media_candidates = set()

                def on_response(resp):
                    u = resp.url
                    if "pbs.twimg.com/media" in u:
                        media_candidates.add(u)

                page.on("response", on_response)

                url = f"https://x.com/i/web/status/{tweet_id}"
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(900)

                # DOM media candidates
                imgs = page.locator('img[src*="pbs.twimg.com/media"]')
                cnt = await imgs.count()
                for i in range(min(cnt, 12)):
                    src = await imgs.nth(i).get_attribute("src")
                    if src:
                        media_candidates.add(src)

                best = await fetch_best_media(context, list(media_candidates))
                new_png = None
                new_m = None
                method = None

                if best is not None:
                    new_png, new_m, _best_url = best
                    method = "direct_media"
                else:
                    lb = await screenshot_lightbox(page)
                    if lb is not None:
                        new_png, new_m = lb
                        method = "lightbox_screenshot"

                if new_png is None or new_m is None:
                    unchanged += 1
                    continue

                if should_replace(old_m, new_m):
                    out_path.write_bytes(new_png)
                    improved += 1
                    if len(improved_samples) < 20:
                        improved_samples.append({
                            "file": file_name,
                            "tweet_id": tweet_id,
                            "method": method,
                            "old": old_m,
                            "new": new_m,
                        })
                else:
                    unchanged += 1

            except Exception as e:
                failed += 1
                if len(failed_samples) < 20:
                    failed_samples.append({"file": file_name, "tweet_id": tweet_id, "reason": str(e)[:180]})
            finally:
                # Remove listeners to avoid accumulation
                try:
                    page.remove_listener("response", on_response)
                except Exception:
                    pass

        await browser.close()

    # Regenerate thumb_data for brand_visual only, from clean/*.png
    vt = json.loads(VISUAL_TAGS_FILE.read_text())
    target_set = set(targets)
    for item in vt.get("items", []):
        f = item.get("file")
        if f in target_set:
            p = CLEAN_DIR / f
            if not p.exists():
                continue
            with Image.open(p) as im:
                rgb = im.convert("RGB")
                rgb.thumbnail((160, 160), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                rgb.save(buf, format="WEBP", quality=75, method=6)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                item["thumb_data"] = f"data:image/webp;base64,{b64}"

    vt["count"] = len(vt.get("items", []))
    VISUAL_TAGS_FILE.write_text(json.dumps(vt, ensure_ascii=False, indent=2) + "\n")

    report = {
        "scope": "brand_visual",
        "processed": processed,
        "improved": improved,
        "unchanged": unchanged,
        "failed": failed,
        "improved_samples": improved_samples,
        "failed_samples": failed_samples,
    }
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
