# Typography V3 Rollout Report

## Scope
- Dataset: `analysis/visual_tags.json`
- Items processed: **447**
- Method: conservative computer-vision heuristics (no OCR dependency)
- Policy enforced:
  - If meaningful readable typography is not present => `typo_present_v3=false`, `typo_primary_v3=no_typo`, `typo_case_v3=na`
  - If typography is present but uncertain => `typo_primary_v3=unknown`
  - Never default to `sans`

## Distribution — typo_present_v3
| value | count | pct |
|---|---:|---:|
| True | 319 | 71.36% |
| False | 128 | 28.64% |

## Distribution — typo_primary_v3
| value | count | pct |
|---|---:|---:|
| no_typo | 128 | 28.64% |
| unknown | 34 | 7.61% |
| sans | 81 | 18.12% |
| serif | 0 | 0.00% |
| mixed | 104 | 23.27% |
| display | 100 | 22.37% |

## Distribution — typo_case_v3
| value | count | pct |
|---|---:|---:|
| na | 128 | 28.64% |
| unknown | 45 | 10.07% |
| mixed | 33 | 7.38% |
| upper | 1 | 0.22% |
| lower | 240 | 53.69% |

## Confidence
- mean typo_confidence_v3: **0.6820**
- min typo_confidence_v3: **0.3148**
- max typo_confidence_v3: **1.0000**

## Heuristic rationale
- Text presence is decided from connected components + line clustering + occupied text-like area.
- The threshold is intentionally conservative to reduce false positives from illustrations, logos, or texture.
- Style classification (serif/sans/display/mixed) is inferred only when shape cues are sufficiently separated; otherwise `unknown`.
- Case classification is inferred from component-height and line-uniformity proxies only; uncertain cases remain `unknown`.

