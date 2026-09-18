# -*- coding: utf-8 -*-
{
    'name': "Pointage ZKTeco — envoi des employés vers BioTime",
    'summary': "Crée et met à jour les employés dans BioTime depuis Odoo (matricule, PIN, zone).",
    'description': """
Complément d'`itv_zk_connector`, qui ne fait que lire BioTime. Ce module écrit :
un employé Odoo (matricule = emp_code, PIN = device_password) est envoyé à BioTime,
qui le distribue ensuite aux pointeuses de sa zone.

Les envois passent par la file `itv.zk.outbox` (opération « Employé ») : chaque
tentative laisse une trace, les erreurs sont rejouables, et rien n'est envoyé si la
connexion est en lecture seule.
""",
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Attendances',
    'license': 'LGPL-3',
    'author': "iTVerse",
    'depends': ['itv_zk_connector'],
    'data': [
        'data/ir_cron.xml',
        'views/zk_backend_views.xml',
        'views/hr_employee_views.xml',
    ],
    'installable': True,
}
