website = env['website'].browse(1)
View = env['ir.ui.view']
report = []

def site_view(key):
    specific = View.with_context(active_test=False).search([('key', '=', key), ('website_id', '=', website.id)], limit=1)
    if specific:
        return specific
    generic = View.with_context(active_test=False).search([('key', '=', key), ('website_id', '=', False)], limit=1)
    return generic.with_context(website_id=website.id)

def step(label, function):
    try:
        with env.cr.savepoint():
            result = function()
        report.append('OK    ' + label + ((' : ' + str(result)) if result else ''))
        return True
    except Exception as exc:
        report.append('ECHEC ' + label + ' : ' + str(exc).replace('\n', ' ')[:300])
        return False

STATES = __STATES__
changed, failed, missing = 0, [], []
for key, active in sorted(STATES.items()):
    view = site_view(key)
    if not view:
        missing.append(key)
        continue
    if view.active == active:
        continue
    if step('%s -> %s' % (key, 'actif' if active else 'inactif'), lambda view=view, active=active: view.write({'active': active})):
        changed += 1
    else:
        failed.append(key)
report = [line for line in report if line.startswith('ECHEC')]
report.append('variantes : %d changées, %d refusées (%s), absentes en 19 : %s' % (changed, len(failed), ', '.join(failed) or '-', ', '.join(missing) or 'aucune'))

step("pied de page appel à l'action (vue mc2 1654)", lambda: site_view('website.template_footer_call_to_action').write({'arch': __ARCH_1654__}))
def custom_snippet():
    popup_key = 'website.s_newsletter_subscribe_popup_3ee0312367df46abb39f6ea49b851d2d'
    if not View.search_count([('key', '=', popup_key), ('website_id', '=', website.id)]):
        View.create({'name': 'Popup Newsletter', 'key': popup_key, 'type': 'qweb', 'website_id': website.id, 'arch': __ARCH_2543__})
        snippets = View.search([('key', '=', 'website.snippets'), ('website_id', '=', False)], limit=1)
        View.create({'name': 'Popup Newsletter (bloc personnalisé)', 'key': 'website.snippets.' + popup_key.split('.', 1)[1],
                     'type': 'qweb', 'mode': 'extension', 'inherit_id': snippets.id, 'website_id': website.id, 'arch': __ARCH_2544__})
    return 'bloc personnalisé présent'
step('bloc personnalisé popup newsletter (vues mc2 2543 et 2544)', custom_snippet)

env.cr.commit()
print('\n'.join('site: ' + line for line in report))
arch = site_view('portal.portal_layout').arch
print('portal_layout 19 (lines with container / account / h3):')
for number, line in enumerate(arch.splitlines(), 1):
    if 'container' in line or 'ccount' in line or '<h3' in line:
        print('  %3d %s' % (number, line.strip()[:170]))
