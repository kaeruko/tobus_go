from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)  # まずChromeで
    context = browser.new_context(locale="ja-JP")
    page = context.new_page()
    print("goto...")
    page.goto("https://www.yodobashi.com/", wait_until="domcontentloaded", timeout=30000)
    print("url:", page.url)
    print("title:", page.title())
    page.wait_for_timeout(5000)
    browser.close()
