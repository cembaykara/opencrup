#!/usr/bin/env python3
"""Capture README screenshots of the running OpenCrup app (Playwright/Chromium).

Usage: python3 scripts/screenshot.py [session_id]
Defaults to a bundled demo conversation if no id is given.
"""
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4322"  # mock-data dev build (scripts/dev_mock.py)
DOCS = "docs"
SESSION = sys.argv[1] if len(sys.argv) > 1 else "ses_webapp_1"


def shoot(page, url, selector, out):
    page.goto(url, wait_until="load", timeout=30000)
    page.wait_for_selector(selector, state="visible", timeout=20000)
    page.wait_for_timeout(400)  # let layout/animations settle
    page.screenshot(path=out)
    print(f"  {out}  <-  {url}")


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=2)

    print("home:")
    shoot(page, f"{BASE}/", "#home-cards .source-card", f"{DOCS}/home.png")

    print("opencode list:")
    shoot(page, f"{BASE}/?source=opencode", "#session-list .session-item", f"{DOCS}/opencode_view.png")

    print("open conversation:")
    shoot(page, f"{BASE}/?source=opencode&session={SESSION}", "#msg-list .msg", f"{DOCS}/conversation_view.png")

    browser.close()
print("done")
