import sys
from playwright.sync_api import sync_playwright
OUT = sys.argv[1]
SITES = {'mc2_odoo18': ('http://127.0.0.1:19069', 'mc2'), 'nabi_odoo19': ('http://127.0.0.1:20069', 'multiceram_nabi')}
PAGES = {'anomalies_feb_fixed': '/my/attendance/get_anomalie?start_day=2026-02-16'}
with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
    for label, (base, db) in SITES.items():
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale='fr-FR')
        page = ctx.new_page()
        page.goto(base + '/web/login?db=' + db, wait_until='networkidle')
        page.request.post(base + '/web/session/authenticate', data={"jsonrpc": "2.0", "method": "call", "params": {"db": db, "login": "admin", "password": "admin"}})
        for name, path in PAGES.items():
            page.goto(base + path, wait_until='networkidle', timeout=180000); page.wait_for_timeout(2500)
            page.screenshot(path='%s/full_%s_%s.png' % (OUT, name, label))
            print(label, name, page.url)
        ctx.close()
    browser.close()
