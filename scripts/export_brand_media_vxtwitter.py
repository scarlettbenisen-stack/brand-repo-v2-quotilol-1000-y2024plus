#!/usr/bin/env python3
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlencode, urlunparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROOT = Path(__file__).resolve().parents[1]
LINKS_FILE = ROOT / "analysis" / "brand_twitter_links.txt"
OUT_DIR = ROOT / "analysis" / "extracted_brand_full"
REPORT_FILE = ROOT / "analysis" / "extracted_brand_full_report.json"

USER_AGENT = "Mozilla/5.0 (compatible; brand-export/1.0; +https://github.com)"


def read_links(path: Path):
    links = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            links.append(line)
    return links


def extract_tweet_id(url: str):
    m = re.search(r"/(?:status|statuses)/(\d+)", url)
    return m.group(1) if m else None


def http_get_json(url: str, timeout=25):
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def http_download(url: str, out_path: Path, timeout=60):
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    out_path.write_bytes(data)


def normalize_pbs_url(url: str):
    # Prefer orig > 4096x4096 > large for pbs.twimg.com
    try:
        p = urlparse(url)
    except Exception:
        return url
    if "pbs.twimg.com" not in p.netloc:
        return url

    q = parse_qs(p.query)
    if "name" in q:
        q["name"] = ["orig"]
    elif p.path:
        pass
    new_query = urlencode(q, doseq=True)
    normalized = urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))

    # If no query size markers, append one
    if "name=" not in normalized:
        sep = "&" if "?" in normalized else "?"
        normalized = f"{normalized}{sep}name=orig"

    return normalized


def collect_media_urls(obj):
    urls = []

    def add(u):
        if isinstance(u, str) and u.startswith("http"):
            urls.append(u)

    def walk(x):
        if isinstance(x, dict):
            # direct known fields
            for key in ("url", "media_url", "mediaUrl", "download", "src", "thumbnail_url", "thumbnailUrl"):
                if key in x:
                    add(x[key])

            # common media containers
            for key in ("media_extended", "mediaURLs", "media", "extended_media", "extended_entities", "entities"):
                if key in x:
                    walk(x[key])

            # video variants (Twitter shape)
            for key in ("variants", "video_info"):
                if key in x:
                    walk(x[key])

            # nested tweet object (vxtwitter sometimes nests)
            for key in ("tweet", "quoted_tweet", "retweeted_tweet", "retweeted_status", "quoted_status"):
                if key in x:
                    walk(x[key])

            # generic walk all
            for v in x.values():
                walk(v)

        elif isinstance(x, list):
            for i in x:
                walk(i)

    walk(obj)

    # keep only media-ish urls
    mediaish = []
    for u in urls:
        ul = u.lower()
        if any(h in ul for h in ["pbs.twimg.com", "video.twimg.com", "twimg.com/ext_tw_video", "amplify_video", "imgur", "cdn"]):
            mediaish.append(u)
        elif any(ext in ul for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov"]):
            mediaish.append(u)

    # de-dupe preserve order
    seen = set()
    out = []
    for u in mediaish:
        u2 = normalize_pbs_url(u) if "pbs.twimg.com" in u else u
        if u2 not in seen:
            seen.add(u2)
            out.append(u2)
    return out


def ext_from_url(url: str):
    p = urlparse(url)
    path = p.path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov"):
        if path.endswith(ext):
            return ext
    q = parse_qs(p.query)
    if "format" in q and q["format"]:
        fmt = q["format"][0].lower()
        if fmt in ("jpg", "jpeg", "png", "webp", "gif"):
            return "." + fmt
    if "video.twimg.com" in p.netloc or "twimg.com/ext_tw_video" in url:
        return ".mp4"
    return ".bin"


def fetch_with_retries(tweet_id: str, retries=3):
    url = f"https://api.vxtwitter.com/Twitter/status/{tweet_id}"
    last_err = None
    for i in range(retries):
        try:
            return http_get_json(url)
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
    raise last_err


def download_with_retries(url: str, out_path: Path, retries=3):
    last_err = None
    candidates = [url]
    if "pbs.twimg.com" in url and "name=orig" in url:
        candidates.extend([
            url.replace("name=orig", "name=4096x4096"),
            url.replace("name=orig", "name=large"),
        ])

    for candidate in candidates:
        for i in range(retries):
            try:
                http_download(candidate, out_path)
                if out_path.exists() and out_path.stat().st_size > 0:
                    return candidate
            except Exception as e:
                last_err = e
                if i < retries - 1:
                    time.sleep(1.0 * (i + 1))
        if out_path.exists() and out_path.stat().st_size == 0:
            out_path.unlink(missing_ok=True)
    raise last_err if last_err else RuntimeError("download failed")


def main():
    links = read_links(LINKS_FILE)
    tweet_ids = []
    for u in links:
        tid = extract_tweet_id(u)
        if tid:
            tweet_ids.append((tid, u))

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    report_items = []
    ok = 0
    total_files = 0

    for idx, (tid, src_url) in enumerate(tweet_ids, 1):
        print(f"[{idx}/{len(tweet_ids)}] {tid}", flush=True)
        item = {
            "tweet_id": tid,
            "url": src_url,
            "status": "failed",
            "files": [],
            "error": None,
        }

        try:
            payload = fetch_with_retries(tid)
            media_urls = collect_media_urls(payload)
            if not media_urls:
                raise RuntimeError("no media URLs found")

            saved = []
            for n, media_url in enumerate(media_urls, 1):
                ext = ext_from_url(media_url)
                out_name = f"tweet_{tid}_{n}{ext}"
                out_path = OUT_DIR / out_name
                used_url = download_with_retries(media_url, out_path)
                saved.append(str(out_path))
                if used_url != media_url:
                    print(f"  fallback URL used: {used_url}")

            item["status"] = "ok"
            item["files"] = saved
            ok += 1
            total_files += len(saved)

        except Exception as e:
            item["error"] = str(e)

        report_items.append(item)

    report = {
        "total_tweets": len(tweet_ids),
        "ok_tweets": ok,
        "failed_tweets": len(tweet_ids) - ok,
        "total_files": total_files,
        "items": report_items,
    }

    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["total_tweets", "ok_tweets", "failed_tweets", "total_files"]}, indent=2))
    print(f"Wrote report: {REPORT_FILE}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
