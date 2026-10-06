"""Real browser identity, tab synchronization and private-cache checks."""

import os
import threading

import pytest
from tests.v2.test_security import PASSWORD, seed
from werkzeug.serving import make_server

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Set RUN_BROWSER_TESTS=1"
    ),
]


def test_multi_tab_logout_switch_and_private_cache(v2app):
    from playwright.sync_api import sync_playwright

    app, factory = v2app
    seed(factory)
    from tests.v2.test_workflows import product

    product(factory)
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            options = {"headless": True}
            if os.environ.get("BROWSER_CHANNEL"):
                options["channel"] = os.environ["BROWSER_CHANNEL"]
            browser = pw.chromium.launch(**options)
            context = browser.new_context(base_url=f"http://127.0.0.1:{server.server_port}")
            page = context.new_page()
            page.goto("/login")
            page.locator('[name="username"]').fill("alice")
            page.locator('[name="password"]').fill(PASSWORD)
            page.locator('button[type="submit"]').click()
            page.wait_for_url("**/")
            page.wait_for_function("document.documentElement.style.visibility !== 'hidden'")
            old_context = page.locator('meta[name="auth-context"]').get_attribute("content")
            other = context.new_page()
            other.goto("/settings")
            other.wait_for_function("document.documentElement.style.visibility !== 'hidden'")
            other.evaluate("ledgerIdentity.logout()")
            page.wait_for_url("**/login")
            other.wait_for_url("**/login")
            page.locator('[name="username"]').fill("bob")
            page.locator('[name="password"]').fill(PASSWORD)
            page.locator('button[type="submit"]').click()
            page.wait_for_url("**/")
            other.wait_for_url("**/")
            page.wait_for_function("document.documentElement.style.visibility !== 'hidden'")
            assert page.locator('meta[name="auth-context"]').get_attribute("content") != old_context
            assert context.request.get("/api/auth/me").json()["username"] == "bob"
            assert context.request.get("/api/positions").headers["cache-control"] == "no-store"
            page.goto("/sources")
            page.wait_for_function("document.querySelector('#source-product').value !== ''")
            page.locator("#source-name").fill("Public test source")
            page.locator("#source-url").fill("https://bank.example/nav")
            page.locator("#source-code").fill("P1")
            page.locator("#source-form [type=submit]").click()
            page.get_by_role("heading", name="Public test source · v1 · 草稿").wait_for()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=".tmp/source-mobile.png", full_page=True)
            page.goto("/settings")
            page.go_back()
            page.wait_for_function("document.documentElement.style.visibility !== 'hidden'")
            assert page.locator('meta[name="auth-context"]').get_attribute("content") != old_context
            # The service worker may cache static assets, never private HTML or APIs.
            urls = page.evaluate("""async () => {
                const all = await Promise.all((await caches.keys()).map(async key =>
                    (await (await caches.open(key)).keys()).map(r => new URL(r.url).pathname)));
                return all.flat();
            }""")
            assert all(url.startswith("/static/") or url == "/offline" for url in urls)
            page.evaluate("navigator.serviceWorker.ready")
            # Admin-only CCB controls load after the same identity boundary.
            page.evaluate("ledgerIdentity.logout()")
            page.wait_for_url("**/login")
            page.locator('[name="username"]').fill("admin")
            page.locator('[name="password"]').fill(PASSWORD)
            page.locator('button[type="submit"]').click()
            page.wait_for_url("**/")
            page.goto("/sources")
            page.locator("#ccb-discover").wait_for()
            page.wait_for_function("document.querySelector('#ccb-product').value !== ''")
            assert page.locator("#ccb-mapping").is_hidden()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            context.set_offline(True)
            page.goto("/settings", wait_until="domcontentloaded")
            page.get_by_role("heading", name="网络连接中断").wait_for()
            assert "B private" not in page.content()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
