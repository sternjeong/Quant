import sys
from playwright.sync_api import sync_playwright

PATH = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12/final_report.html"
OUT = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1000, "height": 1200})
    errors = []
    page.on("console", lambda msg: errors.append(f"[{msg.type}] {msg.text}") if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(f"[pageerror] {exc}"))
    page.goto(f"file://{PATH}")
    page.wait_for_timeout(800)

    print("=== console/page errors ===")
    for e in errors:
        print(e)
    if not errors:
        print("(none)")

    # 각 섹션 스크린샷
    page.screenshot(path=f"{OUT}/shot_top.png")
    for sel, name in [("#by-ticker", "divbar"), ("#by-sector", "dumbbell"),
                       ("#tuning", "tuning"), ("#cases", "cases"), ("#table", "table")]:
        el = page.query_selector(sel)
        if el:
            el.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            page.screenshot(path=f"{OUT}/shot_{name}.png", clip=el.bounding_box())
        else:
            print("missing section", sel)

    # dark mode
    page.emulate_media(color_scheme="dark")
    page.reload()
    page.wait_for_timeout(500)
    page.screenshot(path=f"{OUT}/shot_dark_top.png")
    el = page.query_selector("#by-ticker")
    if el:
        el.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        page.screenshot(path=f"{OUT}/shot_dark_divbar.png", clip=el.bounding_box())

    browser.close()
print("DONE")
