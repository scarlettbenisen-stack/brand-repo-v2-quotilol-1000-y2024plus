# THUMBNAIL V2 REPORT

## Scope
Quality upgrade of thumbnails for `brand_visual` items using local HD assets only (no re-scraping).

## Inputs Used
- `analysis/extracted_brand_full_report.json`
- `analysis/extracted_brand_full/` (local HD images/videos)
- `analysis/visual_tags.json`
- `index.html`

## Method
1. Built mapping `tweet_id -> best local image` from extracted report:
   - kept only image files (`.jpg/.jpeg/.png/.webp`)
   - selected the largest resolution image per tweet (`width * height` max)
2. Generated V2 thumbnails from mapped HD sources:
   - output format: WebP
   - target max side: `320px`
   - quality: `80`
   - enhancement: light contrast boost (`1.05`) + unsharp mask (`radius=1.2, percent=110, threshold=2`)
3. Stored thumbnails as static files in `previews_v2/` (instead of base64 embedding) to keep payload GitHub Pages-friendly.
4. Updated `analysis/visual_tags.json`:
   - for `brand_visual` items only: added `thumb_v2` path (`./previews_v2/tweet_<id>.webp`) where available
   - non-brand classes left unchanged (continue using existing `thumb_data` / fallback behavior)
5. Updated `index.html` to prefer:
   - `thumb_v2` -> `thumb_data` -> original image fallback

## Results
- Brand items total: **447**
- Brand items upgraded with V2 thumb: **444**
- Missing HD mapping: **3**
- Generation errors: **0**
- V2 thumbnail files: **444** (`previews_v2/*.webp`)
- Total V2 payload size: **3,506,768 bytes** (~3.35 MB)

## Missing / Limitations
The following brand tweet IDs had no usable local HD image in extracted report mapping:
- `1995945199194017925`
- `2013617128088162489`
- `2013759209318342865`

Notes:
- If a tweet only had video or missing media locally, no V2 thumb could be generated.
- Existing `thumb_data` remains available as fallback.
- This pass does not crop/reframe composition; it performs resize + light enhancement only.
