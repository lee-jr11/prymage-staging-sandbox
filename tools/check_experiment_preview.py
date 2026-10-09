"""Browser checks for synthetic assignment, event attribution and privacy."""
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright


def check(path, channel='msedge'):
    ga4 = 'Pilot GA4 loader is gated' in path.read_text(encoding='utf-8')
    prefix = 'pilot_' if ga4 else ''
    with sync_playwright() as runner:
        browser = runner.chromium.launch(channel=channel, headless=True)
        try:
            for variant in ('control', 'assessment'):
                for width in (1280, 390):
                    context = browser.new_context(viewport={'width':width,'height':900})
                    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(path.resolve().as_uri()) else route.abort())
                    page = context.new_page()
                    page.on('dialog', lambda dialog: dialog.accept())
                    page.goto(path.resolve().as_uri() + '?variant=' + variant)
                    assert variant in page.locator('#experiment-status').inner_text()
                    if variant == 'assessment' and width == 1280:
                        screenshot = Path('var/experiment-preview/assessment.png')
                        screenshot.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(screenshot), full_page=True)
                    if ga4:
                        assert page.locator('script[src*="googletagmanager"]').count() == 0
                        assert page.evaluate("window['ga-disable-G-EP0Y94K2B6']") is True
                    page.locator('#btn-demo-cta').click()
                    page.locator('#btn-submit-lead').click()
                    events = page.evaluate('Array.from(dataLayer, x => Array.from(x)).filter(x => x[0] === "event")')
                    assert not any(x[1]==prefix+'generate_lead' for x in events)
                    page.locator('#contact-name').fill('Private Test Person')
                    page.locator('#contact-email').fill('private@example.com')
                    page.locator('#btn-submit-lead').click()
                    events = page.evaluate('Array.from(dataLayer, x => Array.from(x)).filter(x => x[0] === "event")')
                    assert [x[1] for x in events] == [prefix+x for x in ('experiment_exposure','demo_interest','generate_lead')]
                    assert all(x[2]['experiment_variant']==variant and x[2]['data_kind']=='synthetic' for x in events)
                    assert 'private@example.com' not in str(events) and 'Private Test Person' not in str(events)
                    other = 'assessment' if variant=='control' else 'control'
                    page.goto(path.resolve().as_uri() + '?variant=' + other)
                    assert variant in page.locator('#experiment-status').inner_text()
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    context.close()
                    if ga4:
                        context = browser.new_context(viewport={'width':width,'height':900})
                        loaded = []
                        def intercept(route):
                            if route.request.url.startswith(path.resolve().as_uri()):
                                route.continue_()
                            elif route.request.url == 'https://www.googletagmanager.com/gtag/js?id=G-EP0Y94K2B6':
                                loaded.append(route.request.url)
                                route.fulfill(status=200,content_type='application/javascript',body='// Mock GA4 loader; no external telemetry.')
                            else:
                                route.abort()
                        context.route('**/*',intercept)
                        page = context.new_page()
                        page.goto(path.resolve().as_uri()+'?variant='+variant+'&telemetry=ga4-test')
                        assert len(loaded)==1
                        assert page.evaluate("window['ga-disable-G-EP0Y94K2B6']") is False
                        assert 'Pilot GA4 test enabled' in page.locator('#experiment-status').inner_text()
                        context.close()
        finally:
            browser.close()


if __name__ == '__main__':
    check(Path(sys.argv[1]), channel=None if len(sys.argv)>2 and sys.argv[2]=='chromium' else 'msedge')
    print('Both variants passed desktop/mobile assignment, event and privacy checks')
