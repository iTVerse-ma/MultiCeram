import sys
from playwright.sync_api import sync_playwright
OUT = sys.argv[1]
SITES = {'mc2_odoo18': ('http://127.0.0.1:19069', 'mc2'), 'nabi_odoo19': ('http://127.0.0.1:20069', 'multiceram_nabi')}
with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
    for label, (base, db) in SITES.items():
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale='fr-FR')
        page = ctx.new_page()
        page.goto(base + '/web/login?db=' + db, wait_until='networkidle')
        page.goto(base + '/', wait_until='networkidle'); page.wait_for_timeout(1500)
        print(label, 'anonymous / ->', page.url)
        page.screenshot(path='%s/v3_home_anonymous_%s.png' % (OUT, label))
        page.request.post(base + '/web/session/authenticate', data={"jsonrpc": "2.0", "method": "call", "params": {"db": db, "login": "admin", "password": "admin"}})
        page.goto(base + '/', wait_until='networkidle'); page.wait_for_timeout(1500)
        print(label, 'logged / ->', page.url)
        page.screenshot(path='%s/v3_home_logged_%s.png' % (OUT, label))
        page.goto(base + '/my/attendance/get_anomalie?start_day=2025-10-15', wait_until='networkidle', timeout=120000); page.wait_for_timeout(2500)
        page.screenshot(path='%s/v3_anomalies_%s.png' % (OUT, label))
        ctx.close()
    browser.close()
