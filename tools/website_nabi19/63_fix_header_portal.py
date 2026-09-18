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

# En-tête « boîte » : les modèles d'en-tête s'excluent ; le modèle par défaut doit être désactivé avant.
def header_boxed():
    active_headers = View.with_context(active_test=False).search([('key', '=like', 'website.template_header_%'), ('website_id', '=', website.id), ('active', '=', True)])
    for view in active_headers.filtered(lambda v: v.key not in ('website.template_header_boxed', 'website.template_header_mobile')):
        view.write({'active': False})
    site_view('website.template_header_boxed').write({'active': True})
    return 'en-têtes actifs : ' + ', '.join(View.search([('key', '=like', 'website.template_header_%'), ('website_id', '=', website.id), ('active', '=', True)]).mapped('key'))
step('en-tête boîte (website.template_header_boxed)', header_boxed)

# Mise en page du portail : même retouche que mc2, sur le modèle source (anglais) pour garder les traductions.
def portal_layout():
    view = site_view('portal.portal_layout').with_context(lang='en_US')
    arch = view.arch
    old = '<div class="container pt-3 pb-5">'
    if old not in arch:
        raise ValueError('motif absent : ' + old)
    view.write({'arch': arch.replace(old, '<div class="">', 1)})
    return 'conteneur du compte sans marges'
step('mise en page du portail (vue mc2 2698)', portal_layout)

env.cr.commit()
print('\n'.join('site: ' + line for line in report))
