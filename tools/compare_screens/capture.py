import sys
from playwright.sync_api import sync_playwright

CODE, OUT = sys.argv[1], sys.argv[2]
SITES = {
    'mc2_odoo18': ('http://127.0.0.1:19069', 'mc2'),
    'nabi_odoo19': ('http://127.0.0.1:20069', 'multiceram_nabi'),
}
PUBLIC = [('home', '/'), ('contact', '/contactus'), ('jobs', '/jobs')]
PRIVATE = [
    ('portal_home', '/my/home'),
    ('per_employee', '/my/attendance/get_punch_stacked?emp_id=%s&start_day=2025-10-01&end_day=2025-10-31' % CODE),
    ('anomalies', '/my/attendance/get_anomalie?start_day=2025-10-15'),
]
with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
    for label, (base, db) in SITES.items():
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale='fr-FR')
        page = ctx.new_page()
        page.goto(base + '/web/login?db=' + db, wait_until='networkidle')
        for name, path in PUBLIC:
            page.goto(base + path, wait_until='networkidle')
            page.wait_for_timeout(1500)
            page.screenshot(path='%s/%s_%s.png' % (OUT, name, label), full_page=(name == 'home'))
        status = page.request.post(base + '/web/session/authenticate', data={"jsonrpc": "2.0", "method": "call", "params": {"db": db, "login": "admin", "password": "admin"}}).json()
        print(label, 'login uid', (status.get('result') or {}).get('uid'))
        for name, path in PRIVATE:
            response = page.goto(base + path, wait_until='networkidle', timeout=120000)
            page.wait_for_timeout(2000)
            page.screenshot(path='%s/%s_%s.png' % (OUT, name, label))
            print(label, name, response.status if response else '-')
        ctx.close()
    browser.close()
