"""Real Chromium smoke test; network blocked to prevent Analytics test pollution.

Requires the optional playwright package and its Chromium runtime.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import sys


def check(source: str, screenshot: Path | None = None, channel: str | None = None):
    from playwright.sync_api import sync_playwright
    prefix = "pilot_" if "Pilot GA4 loader is gated" in source else ""
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        (directory / "index.html").write_bytes(source.encode("utf-8"))
        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(
            QuietHandler, directory=str(directory)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/index.html"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, channel=channel)
                try:
                    for viewport in ({"width": 1280, "height": 900},
                                     {"width": 390, "height": 844}):
                        context = browser.new_context(viewport=viewport, service_workers="block")
                        context.route("**/*", lambda route: route.continue_() if (
                            route.request.url.startswith(f"http://127.0.0.1:{server.server_port}/"))
                                      else route.abort())
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on("dialog", lambda dialog: dialog.accept())
                        page.goto(url)
                        cta = page.locator("#btn-demo-cta")
                        cta.click()
                        events = page.evaluate("Array.from(window.dataLayer, x => Array.from(x))")
                        demos = [entry for entry in events if len(entry) > 1 and
                                 entry[:2] == ["event", prefix + "demo_interest"]]
                        if len(demos) != 1 or demos[0][2]["link_text"] != cta.inner_text().strip():
                            raise AssertionError("Demo handler or CTA analytics label broken")
                        page.locator("#btn-submit-lead").click()
                        before = page.evaluate("Array.from(window.dataLayer, x => Array.from(x))")
                        if any(entry[:2] == ["event", prefix + "generate_lead"] for entry in before):
                            raise AssertionError("Invalid form emitted a lead event")
                        page.locator("#contact-name").fill("Sandbox Visitor")
                        page.locator("#contact-email").fill("sandbox@example.com")
                        page.locator("#contact-region").select_option("NG")
                        page.locator("#btn-submit-lead").click()
                        events = page.evaluate("Array.from(window.dataLayer, x => Array.from(x))")
                        leads = [entry for entry in events if entry[:2] == ["event", prefix + "generate_lead"]]
                        if len(leads) != 1 or leads[0][2]["declared_market"] != "NG":
                            raise AssertionError("Valid form handler broken")
                        if "sandbox@example.com" in str(events) or "Sandbox Visitor" in str(events):
                            raise AssertionError("Personal data leaked into tracking")
                        if not page.locator("#form-feedback").is_visible() or errors:
                            raise AssertionError("Feedback or JavaScript errors: " + str(errors))
                        if page.evaluate("document.documentElement.scrollWidth > innerWidth"):
                            raise AssertionError("Horizontal overflow")
                        if screenshot and viewport["width"] == 1280:
                            screenshot.parent.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(screenshot), full_page=True)
                        context.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    check(Path(sys.argv[1]).read_bytes().decode("utf-8"))
    print("Desktop/mobile browser checks passed; external network was blocked")
