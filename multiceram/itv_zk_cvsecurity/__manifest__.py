# -*- coding: utf-8 -*-
{
    'name': "MultiCeram — CVSecurity (barrière UHF)",
    'summary': "Passages des lecteurs CVSecurity importés comme transactions, au format de BioTime",
    'description': """
Lit les passages des lecteurs UHF dans ZKBio CVSecurity (API v2) et les range dans Odoo comme
des transactions, au même format que celles de BioTime : chaque lecteur est un terminal
(usage, sens, pont UHF), chaque passage une transaction, et le calcul des journées les traite pareil.
""",

    'version': '19.0.1.0.0',
    'category': 'Human Resources/Attendances',
    'author': "iTVerse",
    'depends': ['itv_zk_connector'],
    'data': [
        'data/ir_cron.xml',
        'views/cv_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
}
