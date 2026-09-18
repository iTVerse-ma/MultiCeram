import traceback
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
    except Exception as exc:
        report.append('ECHEC ' + label + ' : ' + str(exc).splitlines()[0][:220])

# 1. Thème et identité
def theme():
    env['ir.module.module'].search([('name', '=', 'theme_cobalt')]).with_context(website_id=website.id).button_choose_theme()
    return website.theme_id.name
step('thème', theme)
step('nom du site et de la société', lambda: website.write({'name': 'Multicerame'}) or env.company.write({'name': 'Multicerame'}) or website.name)

# 2. En-tête et pied de page : état exact de mc2
STATES = __STATES__
def apply_states():
    changed, missing = 0, []
    for key, active in STATES.items():
        view = site_view(key)
        if not view:
            missing.append(key)
            continue
        if view.active != active:
            view.write({'active': active})
            changed += 1
    return '{} changés, absents en 19 : {}'.format(changed, ', '.join(missing) or 'aucun')
step('variantes en-tête / pied de page', apply_states)

# 3. Contenus personnalisés
step("page d'accueil (vue mc2 739)", lambda: site_view('website.homepage').write({'arch': __ARCH_739__}))
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

# 4. Mise en page du portail : même retouche que mc2, appliquée au modèle Odoo 19
def portal_layout():
    view = site_view('portal.portal_layout')
    arch = view.arch
    for old, new in (('<div class="container pt-3 pb-5">', '<div class="">'), ('<h3 class="my-3">My account</h3>', '<h3 class="my-3">Mon compte</h3>')):
        if old not in arch:
            raise ValueError('motif absent dans Odoo 19 : ' + old)
        arch = arch.replace(old, new, 1)
    view.write({'arch': arch})
step('mise en page du portail (vue mc2 2698)', portal_layout)

# 5. Menu principal du site
def menus():
    Menu = env['website.menu']
    root = website.menu_id
    for name, url, sequence in (('Accueil', '/', 10), ('Postes', '/jobs', 59), ('Contactez-nous', '/contactus', 60), ('My Portal', '/my/home', 60)):
        menu = Menu.search([('parent_id', '=', root.id), ('url', '=', url)], limit=1)
        if menu:
            menu.write({'name': name, 'sequence': sequence})
        else:
            Menu.create({'name': name, 'url': url, 'sequence': sequence, 'parent_id': root.id, 'website_id': website.id})
    return ', '.join(m.name + ' ' + m.url for m in Menu.search([('parent_id', '=', root.id)], order='sequence, id'))
step('menu principal', menus)

# 6. Liste de diffusion du site
def newsletter():
    List = env['mailing.list']
    if not List.search_count([('name', '=', 'Newsletter')]):
        List.create({'name': 'Newsletter', 'is_public': True})
    return 'liste Newsletter présente'
step('liste de diffusion Newsletter', newsletter)

env.cr.commit()
print('\n'.join('site: ' + line for line in report))
