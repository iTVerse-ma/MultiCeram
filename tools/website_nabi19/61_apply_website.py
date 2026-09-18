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
# button_choose_theme valide lui-même la transaction : appel direct, hors point de sauvegarde, puis commit.
try:
    theme()
    env.cr.commit()
    report.append('OK    thème : ' + website.theme_id.name)
except Exception as exc:
    env.cr.rollback()
    report.append('ECHEC thème : ' + str(exc).splitlines()[0][:220])
step('nom du site et de la société', lambda: website.write({'name': 'Multicerame'}) or env.company.write({'name': 'Multicerame'}) or website.name)

# 2. En-tête et pied de page : état exact de mc2
STATES = {'website.footer_copyright_company_name': True, 'website.footer_custom': False, 'website.footer_language_selector_code': False, 'website.footer_language_selector_flag': False, 'website.footer_language_selector_inline': True, 'website.footer_language_selector_no_text': False, 'website.footer_no_copyright': False, 'website.header_call_to_action': True, 'website.header_call_to_action_large': True, 'website.header_call_to_action_sidebar': True, 'website.header_call_to_action_stretched': True, 'website.header_hoverable_dropdown': False, 'website.header_language_selector': True, 'website.header_language_selector_code': False, 'website.header_language_selector_flag': False, 'website.header_language_selector_inline': False, 'website.header_language_selector_no_text': False, 'website.header_navbar_pills_style': True, 'website.header_search_box': True, 'website.header_search_box_input': True, 'website.header_social_links': False, 'website.header_text_element': True, 'website.header_visibility_disappears': False, 'website.header_visibility_fade_out': False, 'website.header_visibility_fixed': False, 'website.header_visibility_standard': True, 'website.template_footer_call_to_action': True, 'website.template_footer_centered': False, 'website.template_footer_contact': False, 'website.template_footer_descriptive': False, 'website.template_footer_headline': False, 'website.template_footer_links': False, 'website.template_footer_minimalist': False, 'website.template_footer_slideout': False, 'website.template_header_additional_color_primary': False, 'website.template_header_additional_color_secondary': False, 'website.template_header_boxed': True, 'website.template_header_boxed_align_center': False, 'website.template_header_boxed_align_right': False, 'website.template_header_default': False, 'website.template_header_default_align_center': False, 'website.template_header_default_align_right': False, 'website.template_header_hamburger': False, 'website.template_header_hamburger_align_right': False, 'website.template_header_hamburger_mobile_align_center': False, 'website.template_header_hamburger_mobile_align_right': False, 'website.template_header_mobile': True, 'website.template_header_mobile_align_center': False, 'website.template_header_mobile_align_right': False, 'website.template_header_sales_four': False, 'website.template_header_sales_four_align_center': False, 'website.template_header_sales_four_align_right': False, 'website.template_header_sales_one': False, 'website.template_header_sales_one_align_center': False, 'website.template_header_sales_one_align_right': False, 'website.template_header_sales_three': False, 'website.template_header_sales_two': False, 'website.template_header_sales_two_align_center': False, 'website.template_header_sales_two_align_right': False, 'website.template_header_search': False, 'website.template_header_search_align_center': False, 'website.template_header_search_align_right': False, 'website.template_header_sidebar': False, 'website.template_header_sidebar_align_center': False, 'website.template_header_sidebar_align_right': False, 'website.template_header_stretch': False, 'website.template_header_stretch_align_center': False, 'website.template_header_stretch_align_right': False, 'website.template_header_vertical': False}
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
step("page d'accueil (vue mc2 739)", lambda: site_view('website.homepage').write({'arch': '<t name="Homepage" t-name="website.homepage">\n    <t t-call="website.layout">\n        <t t-set="pageName" t-value="\'homepage\'"/>\n        <div id="wrap" class="oe_structure oe_empty"><div class="s_popup o_newsletter_popup o_snippet_invisible d-none" data-name="Popup Newsletter" data-vcss="001" data-snippet="s_newsletter_subscribe_popup" id="sPopup1758649012505" data-invisible="1">\n        <div class="modal fade s_popup_middle o_newsletter_modal modal_shown" style="background-color: var(--black-50) !important; display: none;" data-show-after="5000" data-display="onClick" data-consents-duration="7" data-bs-focus="false" data-bs-backdrop="false" tabindex="-1" id="Toujours-le-premier.2" aria-hidden="true">\n            <div class="modal-dialog d-flex">\n                <div class="modal-content oe_structure"><section class="s_text_block pt88 pb64 o_colored_level oe_img_bg o_bg_img_center o_bg_img_origin_border_box" data-snippet="s_text_block" data-name="Text" style="background-position: 0px 100%; background-image: url(&quot;/web/image/website.s_cover_default_image&quot;) !important;">\n                        <div class="container s_allow_columns">\n                            <div class="row">\n                                <div class="col-lg-12 bg-black-50 o_colored_level">\n                                    <h2 style="text-align: center;">Toujours le <b class="o_default_snippet_text">premier</b>.</h2>\n                                    <p style="text-align: center;" class="o_default_snippet_text">Soyez le premier à découvrir toutes les dernières nouvelles, <br/>produits et tendances.</p>\n                                </div>\n                            </div>\n                        </div>\n                    </section>\n                    <div class="s_popup_close js_close_popup o_we_no_overlay o_not_editable o_default_snippet_text" aria-label="Fermer">×</div>\n                    \n                    <section class="s_text_block o_colored_level" data-snippet="s_text_block" data-name="Text">\n                        <div class="container">\n                            <div class="row s_nb_column_fixed g-0">\n                                <div class="col-lg-8 offset-lg-2 pt32 pb32 o_colored_level">\n    <div class="s_newsletter_subscribe_form s_newsletter_list js_subscribe" data-vxml="001" data-list-id="1" data-name="Newsletter Form" data-snippet="s_newsletter_subscribe_form">\n        <div class="js_subscribed_wrap d-none">\n            <p class="h4-fs text-center text-success o_default_snippet_text"><i class="fa fa-check-circle-o" role="img"/> Merci pour votre inscription !</p>\n        </div>\n        <div class="js_subscribe_wrap">\n            <div class="input-group">\n                <input type="email" name="email" class="js_subscribe_value form-control" placeholder="johnsmith@example.com"/>\n                <a role="button" href="#" class="btn btn-primary js_subscribe_btn o_submit o_default_snippet_text">S\'inscrire</a>\n            </div>\n        </div>\n    </div>\n                                </div>\n                            </div>\n                        </div>\n                    </section>\n                </div>\n            </div>\n        </div>\n    </div></div>\n    </t>\n</t>'}))
step("pied de page appel à l'action (vue mc2 1654)", lambda: site_view('website.template_footer_call_to_action').write({'arch': '<data inherit_id="website.layout" name="Call-to-Action" active="False">\n    <xpath expr="//div[@id=\'footer\']" position="replace">\n        <div id="footer" class="oe_structure oe_structure_solo" t-ignore="true" t-if="not no_footer">\n            <section class="s_call_to_action pt64 pb64" data-name="Appel à l\'action">\n                <div class="container">\n                    <div class="row">\n                        <div class="col-lg-9">\n                            <h3>Plus de 50.000 entreprises utilisent Odoo pour développer leurs activités.</h3>\n                            <p class="lead">Rejoignez-nous et passez à la vitesse supérieure.</p>\n                        </div>\n                        <div class="col-lg-3 o_colored_level">\n                            <a class="btn btn-primary mb-2" href="#Toujours-le-premier.2">Bouton</a> <a href="/contactus" class="btn btn-primary btn-lg btn-block mb-2">Bouton de démarrage</a>\n                        </div>\n                    </div>\n                </div>\n            </section>\n            <section class="s_text_block" data-snippet="s_text_block" data-name="Text">\n                <div class="container s_allow_columns">\n                    <div class="s_hr pt16 pb16" data-name="Séparateur">\n                        <hr class="w-100 mx-auto" style="border-color: var(--600);"/>\n                    </div>\n                </div>\n            </section>\n            <section class="s_text_block" data-snippet="s_text_block" data-name="Text">\n                <div class="container">\n                    <div class="row">\n                        <div class="col-lg-9">\n                            <p><i class="fa fa-1x fa-fw fa-map-marker me-2"/>250 Executive Park Blvd, Suite 3400 • San Francisco CA 94134 • États-Unis</p>\n                        </div>\n                        <div class="col-lg-3">\n                            <p><i class="fa fa-1x fa-fw fa-envelope me-2"/><a href="mailto:info@yourcompany.example.com">info@yourcompany.example.com</a></p>\n                        </div>\n                    </div>\n                </div>\n            </section>\n        </div>\n    </xpath>\n</data>'}))
def custom_snippet():
    popup_key = 'website.s_newsletter_subscribe_popup_3ee0312367df46abb39f6ea49b851d2d'
    if not View.search_count([('key', '=', popup_key), ('website_id', '=', website.id)]):
        View.create({'name': 'Popup Newsletter', 'key': popup_key, 'type': 'qweb', 'website_id': website.id, 'arch': '<div class="s_popup o_newsletter_popup o_snippet_invisible o_draggable s_custom_snippet" data-vcss="001" data-snippet="s_newsletter_subscribe_popup" id="sPopup1758649012505">\n        <div class="modal fade s_popup_middle o_newsletter_modal modal_shown show" style="background-color: var(--black-50) !important; display: block;" data-show-after="5000" data-display="onClick" data-consents-duration="7" data-bs-focus="false" data-bs-backdrop="false" tabindex="-1" id="Toujours-le-premier.2" aria-modal="true" role="dialog">\n            <div class="modal-dialog d-flex">\n                <div class="modal-content oe_structure"><section class="s_text_block pt88 pb64 o_colored_level oe_img_bg o_bg_img_center o_bg_img_origin_border_box" data-snippet="s_text_block" data-name="Text" style="background-position: 0px 100%; background-image: url(&quot;/web/image/website.s_cover_default_image&quot;) !important;">\n                        <div class="container s_allow_columns">\n                            <div class="row">\n                                <div class="col-lg-12 bg-black-50 o_colored_level o_draggable">\n                                    <h2 style="text-align: center;">Toujours le <b class="o_default_snippet_text">premier</b>.</h2>\n                                    <p style="text-align: center;" class="o_default_snippet_text">Soyez le premier à découvrir toutes les dernières nouvelles, <br/>produits et tendances.</p>\n                                </div>\n                            </div>\n                        </div>\n                    </section>\n                    <div class="s_popup_close js_close_popup o_we_no_overlay o_not_editable o_default_snippet_text" aria-label="Fermer" contenteditable="false">×</div>\n                    \n                    <section class="s_text_block o_colored_level" data-snippet="s_text_block" data-name="Text">\n                        <div class="container">\n                            <div class="row s_nb_column_fixed g-0">\n                                <div class="col-lg-8 offset-lg-2 pt32 pb32 o_colored_level">\n    <div class="s_newsletter_subscribe_form s_newsletter_list js_subscribe" data-vxml="001" data-list-id="1" data-name="Newsletter Form" data-snippet="s_newsletter_subscribe_form">\n        <div class="js_subscribed_wrap d-none">\n            <p class="h4-fs text-center text-success o_default_snippet_text"><i class="fa fa-check-circle-o" role="img" contenteditable="false">\u200b</i> Merci pour votre inscription !</p>\n        </div>\n        <div class="js_subscribe_wrap">\n            <div class="input-group">\n                <input type="email" name="email" class="js_subscribe_value form-control" placeholder="johnsmith@example.com"/>\n                <a role="button" href="#" class="btn btn-primary js_subscribe_btn o_submit o_default_snippet_text">S\'inscrire</a>\n            </div>\n        </div>\n    </div>\n                                </div>\n                            </div>\n                        </div>\n                    </section>\n                </div>\n            </div>\n        </div>\n    </div>'})
        snippets = View.search([('key', '=', 'website.snippets'), ('website_id', '=', False)], limit=1)
        View.create({'name': 'Popup Newsletter (bloc personnalisé)', 'key': 'website.snippets.' + popup_key.split('.', 1)[1],
                     'type': 'qweb', 'mode': 'extension', 'inherit_id': snippets.id, 'website_id': website.id, 'arch': '<data inherit_id="website.snippets">\n                    <xpath expr="//snippets[@id=\'snippet_custom\']" position="inside">\n                        <t t-snippet="website.s_newsletter_subscribe_popup_3ee0312367df46abb39f6ea49b851d2d" t-thumbnail="oe-thumbnail"/>\n                    </xpath>\n                </data>'})
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
