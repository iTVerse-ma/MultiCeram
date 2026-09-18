# -*- coding: utf-8 -*-
{
    'name': "nabi_hr",
    'summary': "Pointage ZKTeco BioTime et pages RH de MultiCeram (module d'origine, porté sur Odoo 19)",
    'description': """
Portage à l'identique du module nabi_hr de MultiCeram (Odoo 18) vers Odoo 19.

Les écrans et champs créés directement dans la base de production mc2 (Studio, vues du
site web, groupes, menus « ZK ») sont repris dans le code, sans changement de comportement.
    """,
    'author': "nabi (module d'origine), iTVerse (portage Odoo 19)",
    'category': 'Human Resources',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',

    'depends': ['base', 'hr', 'hr_holidays', 'portal', 'website'],

    'data': [
        'security/nabi_hr_security.xml',
        'security/ir.model.access.csv',
        'data/nabi_hr_data.xml',
        'views/templates.xml',
        'views/resteday.xml',
        'views/overtime.xml',
        'views/leaves.xml',
        'views/restaurant.xml',
        'views/views.xml',
        'views/anomalies.xml',
        'views/legacy_templates.xml',
        'views/backoffice.xml',
    ],
    'demo': [
        'demo/demo.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            "nabi_hr/static/libs/sheetjs/xlsx.full.min.js",
            'nabi_hr/static/src/portal_component/**/*',
        ],
        # Chargé après le reste, comme le JavaScript personnalisé du site dans mc2.
        'web.assets_frontend_lazy': [
            'nabi_hr/static/src/website_custom/user_custom_javascript.js',
        ],
    },

    'installable': True,
    'application': True,
}
