# -*- coding: utf-8 -*-
{
    'name': "Portail libre-service RH",
    'summary': "Espace employé : mes pointages, mes congés, mes heures supplémentaires, mes documents.",
    'description': """
Portail destiné aux employés **sans compte interne Odoo**. Chaque employé y consulte ses propres
journées (pointages, heures, anomalies), demande ses congés et suit ses heures supplémentaires.

Principes :
- l'employé est toujours déduit de l'utilisateur connecté, jamais d'un paramètre d'URL ;
- les lectures et écritures passent par `sudo()` **après** ce filtrage, car un utilisateur portail
  n'a aucun droit sur les modèles RH ;
- rien n'est validé côté employé : les demandes suivent le circuit natif d'Odoo (congés) ou
  attendent un traitement RH (anomalies, documents).
""",
    'version': '19.0.1.1.0',
    'category': 'Human Resources/Attendances',
    'license': 'LGPL-3',
    'author': "iTVerse",
    'depends': ['itv_zk_attendance', 'hr_holidays', 'portal', 'auth_signup'],
    'data': [
        'security/ir.model.access.csv',
        'views/portal_templates.xml',
        'views/portal_cleanup.xml',
        'views/hr_leave_type_views.xml',
        'views/attendance_day_views.xml',
        'wizard/anomaly_wizard_views.xml',
        'wizard/portal_provision_views.xml',
        'report/portal_activation_report.xml',
    ],
    'installable': True,
}
