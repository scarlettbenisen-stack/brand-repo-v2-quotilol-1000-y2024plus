#!/usr/bin/env python3
"""
Rebuild typography V3 fields for all items in analysis/visual_tags.json
without OCR dependencies (no tesseract).

V3 fields added (v2 untouched):
- typo_present_v3: bool
- typo_primary_v3: serif|sans|mixed|display|no_typo|unknown
- typo_case_v3: upper|lower|mixed|unknown|na
- typo_confidence_v3: float [0..1]
"""

from __future__ import annotations

import json
from pathlib import Path
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = ROOT / "analysis" / "visual_tags.json"
REPORT_PATH = ROOT / "analysis" / "typo_v3_report.md"


@dataclass
class TextStats:
    n_components: int
    n_line_components: int
    n_lines: int
    line_balance: float
    edge_density: float
    text_area_ratio: float
    char_height_cv: float
    width_height_median: float
    stroke_cv: float
    roundness_mean: float


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def safe_read_gray(path: Path):
    if not path.exists():
        return None
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    return img


def extract_candidate_components(gray: np.ndarray) -> List[Tuple[int, int, int, int, int]]:
    h, w = gray.shape[:2]
    area_total = h * w

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    th1 = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 9
    )
    th2 = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 9
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    masks = [cv2.morphologyEx(t, cv2.MORPH_OPEN, kernel) for t in (th1, th2)]

    comps: List[Tuple[int, int, int, int, int]] = []
    for mask in masks:
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            x, y, ww, hh, area = stats[i].tolist()
            if area < 18:
                continue
            if area > 0.04 * area_total:
                continue
            if ww < 2 or hh < 4:
                continue
            if hh > h * 0.35:
                continue
            ar = ww / max(hh, 1)
            if ar < 0.08 or ar > 18:
                continue
            fill = area / max(ww * hh, 1)
            if fill < 0.08 or fill > 0.95:
                continue
            comps.append((x, y, ww, hh, area))

    # dedupe near-identical rectangles from inverse/normal threshold passes
    comps.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    dedup: List[Tuple[int, int, int, int, int]] = []
    for c in comps:
        x, y, ww, hh, _ = c
        keep = True
        for d in dedup[-25:]:
            dx, dy, dw, dh, _ = d
            if abs(x - dx) <= 2 and abs(y - dy) <= 2 and abs(ww - dw) <= 2 and abs(hh - dh) <= 2:
                keep = False
                break
        if keep:
            dedup.append(c)
    return dedup


def line_clustering(components: List[Tuple[int, int, int, int, int]]) -> Tuple[int, int, float, float]:
    if not components:
        return 0, 0, 0.0, 0.0

    comps = sorted(components, key=lambda c: c[1] + c[3] * 0.5)
    heights = np.array([c[3] for c in comps], dtype=np.float32)
    med_h = float(np.median(heights)) if len(heights) else 0.0
    tol = max(4.0, med_h * 0.7)

    lines: List[List[Tuple[int, int, int, int, int]]] = []
    for c in comps:
        yc = c[1] + c[3] * 0.5
        placed = False
        for line in lines:
            ymean = np.mean([x[1] + x[3] * 0.5 for x in line])
            if abs(yc - ymean) <= tol:
                line.append(c)
                placed = True
                break
        if not placed:
            lines.append([c])

    strong_lines = []
    n_line_components = 0
    for line in lines:
        if len(line) < 3:
            continue
        line_sorted = sorted(line, key=lambda c: c[0])
        xs = np.array([c[0] for c in line_sorted], dtype=np.float32)
        ws = np.array([c[2] for c in line_sorted], dtype=np.float32)
        gaps = xs[1:] - (xs[:-1] + ws[:-1])
        if len(gaps) == 0:
            continue
        med_gap = float(np.median(np.clip(gaps, 0, None)))
        if med_gap > med_h * 4.5:
            continue
        n_line_components += len(line)
        strong_lines.append(line)

    if not strong_lines:
        return 0, 0, 0.0, med_h

    lengths = np.array([len(l) for l in strong_lines], dtype=np.float32)
    line_balance = float(np.min(lengths) / max(np.max(lengths), 1.0)) if len(lengths) >= 2 else 1.0
    return len(strong_lines), n_line_components, line_balance, med_h


def estimate_stroke_stats(gray: np.ndarray, components: List[Tuple[int, int, int, int, int]]) -> Tuple[float, float]:
    if not components:
        return 1.0, 0.0
    sample = components[: min(140, len(components))]
    rois = []
    roundnesses = []
    for x, y, w, h, _ in sample:
        patch = gray[max(0, y): y + h, max(0, x): x + w]
        if patch.size < 12:
            continue
        p = cv2.GaussianBlur(patch, (3, 3), 0)
        bw = cv2.adaptiveThreshold(p, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 5)
        fg = np.count_nonzero(bw)
        if fg < 8:
            continue
        dist = cv2.distanceTransform(bw, cv2.DIST_L2, 3)
        vals = dist[dist > 0]
        if vals.size < 4:
            continue
        stroke_mean = float(np.mean(vals))
        stroke_std = float(np.std(vals))
        rois.append((stroke_mean, stroke_std))

        contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            cnt = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(cnt)
            peri = cv2.arcLength(cnt, True)
            if peri > 0:
                roundness = float(4 * np.pi * area / (peri * peri))
                roundnesses.append(roundness)

    if not rois:
        return 1.0, float(np.mean(roundnesses) if roundnesses else 0.0)

    means = np.array([r[0] for r in rois], dtype=np.float32)
    stds = np.array([r[1] for r in rois], dtype=np.float32)
    stroke_cv = float(np.mean(stds / np.maximum(means, 1e-3)))
    roundness_mean = float(np.mean(roundnesses) if roundnesses else 0.0)
    return stroke_cv, roundness_mean


def analyze_text_stats(gray: np.ndarray) -> TextStats:
    h, w = gray.shape[:2]
    edges = cv2.Canny(gray, 80, 180)
    edge_density = float(np.count_nonzero(edges) / (h * w))

    components = extract_candidate_components(gray)
    n_components = len(components)

    n_lines, n_line_components, line_balance, med_h = line_clustering(components)

    if components:
        total_box_area = float(sum(c[2] * c[3] for c in components))
        text_area_ratio = min(total_box_area / (h * w), 1.0)
        heights = np.array([c[3] for c in components], dtype=np.float32)
        char_height_cv = float(np.std(heights) / np.maximum(np.mean(heights), 1e-4))
        wh = np.array([c[2] / max(c[3], 1) for c in components], dtype=np.float32)
        width_height_median = float(np.median(wh))
    else:
        text_area_ratio = 0.0
        char_height_cv = 1.0
        width_height_median = 0.0

    stroke_cv, roundness_mean = estimate_stroke_stats(gray, components)

    return TextStats(
        n_components=n_components,
        n_line_components=n_line_components,
        n_lines=n_lines,
        line_balance=line_balance,
        edge_density=edge_density,
        text_area_ratio=text_area_ratio,
        char_height_cv=char_height_cv,
        width_height_median=width_height_median,
        stroke_cv=stroke_cv,
        roundness_mean=roundness_mean,
    )


def infer_typo_v3(gray: np.ndarray) -> Dict:
    s = analyze_text_stats(gray)

    # Conservative meaningful-text evidence score (0..1)
    comp_score = clamp01((s.n_components - 12) / 45.0)
    line_score = clamp01((s.n_line_components - 8) / 40.0)
    lines_score = clamp01(s.n_lines / 3.0)
    area_score = clamp01((s.text_area_ratio - 0.010) / 0.085)

    presence_score = (
        0.30 * comp_score
        + 0.32 * line_score
        + 0.18 * lines_score
        + 0.20 * area_score
    )

    has_meaningful_typo = (
        presence_score >= 0.43
        and s.n_line_components >= 10
        and s.n_lines >= 1
        and s.text_area_ratio >= 0.010
    )

    if not has_meaningful_typo:
        conf = clamp01(1.0 - presence_score * 0.9)
        return {
            "typo_present_v3": False,
            "typo_primary_v3": "no_typo",
            "typo_case_v3": "na",
            "typo_confidence_v3": round(conf, 4),
            "_debug": s,
        }

    # style inference (conservative; unknown by default when ambiguous)
    display_score = 0.0
    serif_score = 0.0
    sans_score = 0.0

    # display: large variance, irregular forms, thick/variable strokes, sparse lines
    if s.char_height_cv > 0.65:
        display_score += 0.35
    if s.stroke_cv > 0.95:
        display_score += 0.25
    if s.width_height_median > 1.15:
        display_score += 0.15
    if s.n_lines <= 2 and s.text_area_ratio < 0.045:
        display_score += 0.15

    # serif proxy: stroke variation and lower roundness
    if 0.55 <= s.stroke_cv <= 1.05:
        serif_score += 0.30
    if s.roundness_mean < 0.28:
        serif_score += 0.20
    if 0.45 <= s.width_height_median <= 1.10:
        serif_score += 0.15

    # sans proxy: lower stroke variation, smoother contours
    if s.stroke_cv < 0.58:
        sans_score += 0.32
    if s.roundness_mean >= 0.30:
        sans_score += 0.22
    if 0.42 <= s.width_height_median <= 1.05:
        sans_score += 0.12

    # mixed proxy when cues conflict
    top = sorted([
        ("display", display_score),
        ("serif", serif_score),
        ("sans", sans_score),
    ], key=lambda x: x[1], reverse=True)

    style_margin = top[0][1] - top[1][1]
    if top[0][1] < 0.42:
        primary = "unknown"
    elif style_margin < 0.14:
        primary = "mixed"
    else:
        primary = top[0][0]

    # case inference from line uniformity + component-height structure (very conservative)
    upper_score = 0.0
    lower_score = 0.0

    if s.char_height_cv < 0.36:
        upper_score += 0.42
    if s.line_balance > 0.65:
        upper_score += 0.20

    if s.char_height_cv > 0.54:
        lower_score += 0.35
    if s.n_lines >= 2 and s.line_balance < 0.58:
        lower_score += 0.16

    if upper_score >= 0.5 and lower_score < 0.35:
        typo_case = "upper"
    elif lower_score >= 0.5 and upper_score < 0.35:
        typo_case = "lower"
    elif (upper_score >= 0.4 and lower_score >= 0.35) or (0.35 < s.char_height_cv < 0.56):
        typo_case = "mixed"
    else:
        typo_case = "unknown"

    style_conf = top[0][1]
    case_conf = max(upper_score, lower_score)
    conf = clamp01(0.45 * presence_score + 0.35 * style_conf + 0.20 * case_conf)

    return {
        "typo_present_v3": True,
        "typo_primary_v3": primary,
        "typo_case_v3": typo_case,
        "typo_confidence_v3": round(conf, 4),
        "_debug": s,
    }


def resolve_image_path(item: Dict) -> Path:
    thumb = item.get("thumb_v2")
    if thumb:
        p = (ROOT / thumb).resolve()
        if p.exists():
            return p
    return (ROOT / "clean" / item["file"]).resolve()


def render_report(items: List[Dict], counters: Dict[str, Counter], conf_values: List[float], failures: List[str]):
    n = len(items)

    def row(counter: Counter, ordered: List[str]) -> str:
        lines = ["| value | count | pct |", "|---|---:|---:|"]
        for k in ordered:
            c = counter.get(k, 0)
            p = (100.0 * c / n) if n else 0.0
            lines.append(f"| {k} | {c} | {p:.2f}% |")
        for k, c in counter.items():
            if k in ordered:
                continue
            p = (100.0 * c / n) if n else 0.0
            lines.append(f"| {k} | {c} | {p:.2f}% |")
        return "\n".join(lines)

    avg_conf = sum(conf_values) / max(len(conf_values), 1)

    md = []
    md.append("# Typography V3 Rollout Report")
    md.append("")
    md.append("## Scope")
    md.append(f"- Dataset: `analysis/visual_tags.json`")
    md.append(f"- Items processed: **{n}**")
    md.append("- Method: conservative computer-vision heuristics (no OCR dependency)")
    md.append("- Policy enforced:")
    md.append("  - If meaningful readable typography is not present => `typo_present_v3=false`, `typo_primary_v3=no_typo`, `typo_case_v3=na`")
    md.append("  - If typography is present but uncertain => `typo_primary_v3=unknown`")
    md.append("  - Never default to `sans`")
    md.append("")
    md.append("## Distribution — typo_present_v3")
    md.append(row(counters["present"], ["True", "False"]))
    md.append("")
    md.append("## Distribution — typo_primary_v3")
    md.append(row(counters["primary"], ["no_typo", "unknown", "sans", "serif", "mixed", "display"]))
    md.append("")
    md.append("## Distribution — typo_case_v3")
    md.append(row(counters["case"], ["na", "unknown", "mixed", "upper", "lower"]))
    md.append("")
    md.append("## Confidence")
    md.append(f"- mean typo_confidence_v3: **{avg_conf:.4f}**")
    md.append(f"- min typo_confidence_v3: **{min(conf_values) if conf_values else 0:.4f}**")
    md.append(f"- max typo_confidence_v3: **{max(conf_values) if conf_values else 0:.4f}**")
    md.append("")
    md.append("## Heuristic rationale")
    md.append("- Text presence is decided from connected components + line clustering + occupied text-like area.")
    md.append("- The threshold is intentionally conservative to reduce false positives from illustrations, logos, or texture.")
    md.append("- Style classification (serif/sans/display/mixed) is inferred only when shape cues are sufficiently separated; otherwise `unknown`.")
    md.append("- Case classification is inferred from component-height and line-uniformity proxies only; uncertain cases remain `unknown`.")
    md.append("")
    if failures:
        md.append("## Missing/unreadable assets")
        md.append(f"- Count: {len(failures)}")
        for f in failures[:25]:
            md.append(f"  - {f}")
        if len(failures) > 25:
            md.append(f"  - … +{len(failures)-25} more")

    REPORT_PATH.write_text("\n".join(md) + "\n", encoding="utf-8")


def main():
    payload = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    items: List[Dict] = payload.get("items", [])

    counters = {
        "present": Counter(),
        "primary": Counter(),
        "case": Counter(),
    }
    conf_values: List[float] = []
    failures: List[str] = []

    for item in items:
        img_path = resolve_image_path(item)
        gray = safe_read_gray(img_path)
        if gray is None:
            failures.append(item.get("file", str(img_path)))
            result = {
                "typo_present_v3": False,
                "typo_primary_v3": "no_typo",
                "typo_case_v3": "na",
                "typo_confidence_v3": 0.15,
            }
        else:
            result = infer_typo_v3(gray)

        item["typo_present_v3"] = bool(result["typo_present_v3"])
        item["typo_primary_v3"] = result["typo_primary_v3"]
        item["typo_case_v3"] = result["typo_case_v3"]
        item["typo_confidence_v3"] = float(result["typo_confidence_v3"])

        counters["present"][str(item["typo_present_v3"])] += 1
        counters["primary"][item["typo_primary_v3"]] += 1
        counters["case"][item["typo_case_v3"]] += 1
        conf_values.append(item["typo_confidence_v3"])

    fields = payload.get("fields", [])
    for f in ["typo_present_v3", "typo_primary_v3", "typo_case_v3", "typo_confidence_v3"]:
        if f not in fields:
            fields.append(f)
    payload["fields"] = fields

    ANALYSIS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    render_report(items, counters, conf_values, failures)

    print(f"Processed {len(items)} items")
    print("present:", dict(counters["present"]))
    print("primary:", dict(counters["primary"]))
    print("case:", dict(counters["case"]))
    print(f"report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
