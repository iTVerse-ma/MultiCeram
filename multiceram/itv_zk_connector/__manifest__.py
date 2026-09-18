# -*- coding: utf-8 -*-
{
    'name': "Connecteur ZKTeco BioTime",
    'summary': "API BioTime 9.x : terminaux, pointages bruts, employés et départements, journal de synchronisation",
    'description': """
Connecteur ZKTeco BioTime pour Odoo 19, intégré à l'application Présences :
- client API (jeton, reprises, pagination, lecture seule, coupe-circuit) ;
- import incrémental des pointages, réconciliation quotidienne des retards de téléversement ;
- terminaux (usage, sens, santé), employés et départements ;
- journal de synchronisation et file d'envoi vers BioTime ;
- neutralisation des copies de base (aucune écriture vers la production) ;
- menus, paramètres et droits d'accès de Présences.
    """,
    'author': "iTVerse",
    'website': "https://itverse.ma",
    'category': 'Human Resources/Attendances',
    'version': '19.0.1.1.0',
    'license': 'LGPL-3',

    'depends': [
        'hr',
        'hr_attendance',
        'resource',
        'mail',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },

    'data': [
        'security/itv_zk_security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/zk_terminal_views.xml',
        'views/zk_punch_views.xml',
        'views/zk_sync_log_views.xml',
        'views/zk_outbox_views.xml',
        'views/zk_backend_views.xml',
        'views/hr_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],

    'installable': True,
    'application': False,
    'auto_install': False,
}
