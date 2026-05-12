# Typography V3 Rollout Report

## Scope
- Dataset: `analysis/visual_tags.json`
- Items processed: **593**
- Method: conservative computer-vision heuristics (no OCR dependency)
- Policy enforced:
  - If meaningful readable typography is not present => `typo_present_v3=false`, `typo_primary_v3=no_typo`, `typo_case_v3=na`
  - If typography is present but uncertain => `typo_primary_v3=unknown`
  - Never default to `sans`

## Distribution — typo_present_v3
| value | count | pct |
|---|---:|---:|
| True | 538 | 90.73% |
| False | 55 | 9.27% |

## Distribution — typo_primary_v3
| value | count | pct |
|---|---:|---:|
| no_typo | 55 | 9.27% |
| unknown | 24 | 4.05% |
| sans | 189 | 31.87% |
| serif | 0 | 0.00% |
| mixed | 255 | 43.00% |
| display | 70 | 11.80% |

## Distribution — typo_case_v3
| value | count | pct |
|---|---:|---:|
| na | 55 | 9.27% |
| unknown | 22 | 3.71% |
| mixed | 15 | 2.53% |
| upper | 1 | 0.17% |
| lower | 500 | 84.32% |

## Confidence
- mean typo_confidence_v3: **0.7231**
- min typo_confidence_v3: **0.4280**
- max typo_confidence_v3: **1.0000**

## Heuristic rationale
- Text presence is decided from connected components + line clustering + occupied text-like area.
- The threshold is intentionally conservative to reduce false positives from illustrations, logos, or texture.
- Style classification (serif/sans/display/mixed) is inferred only when shape cues are sufficiently separated; otherwise `unknown`.
- Case classification is inferred from component-height and line-uniformity proxies only; uncertain cases remain `unknown`.

