#!/usr/bin/env python3
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parents[1]
AUTH = BASE / 'auth'
AUTH.mkdir(parents=True, exist_ok=True)
STATE = AUTH / 'x_storage_state.json'

print('Open a visible browser. Log in to X manually, then press Enter here.')
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(AUTH / 'chromium-profile'),
        headless=False,
        viewport={"width": 1440, "height": 1200},
    )
    page = ctx.new_page()
    page.goto('https://x.com/home', wait_until='domcontentloaded')
    input('After login is complete and home feed is visible, press Enter... ')
    ctx.storage_state(path=str(STATE))
    print(f'Saved session state: {STATE}')
    ctx.close()
