# -*- coding: utf-8 -*-
{
    'name': "Présences : pointage BioTime MultiCeram",
    'summary': "Journées calculées selon les règles nabi_hr, présences issues des pointages BioTime, heures supplémentaires validées en deux niveaux",
    'description': """
Extension de l'application Présences :
- calcul historique nabi_hr des journées (Pointage par employé, Anomalies, Calcul historique, PDF mensuel) ;
- une présence par jour travaillé, calculée à partir des pointages BioTime ;
- heures supplémentaires natives de Présences alimentées par le calcul historique, avec mise en circuit et validation N1 / N2 ;
- anomalies à traiter (pointage manuel, justification), jours de repos en congé natif ;
- règles d'heures supplémentaires natives désactivées.
    """,
    'author': "iTVerse",
    'website': "https://itverse.ma",
    'category': 'Human Resources/Attendances',
    'version': '19.0.2.3.0',
    'post_init_hook': 'post_init_hook',
    'license': 'LGPL-3',

    'depends': [
        'itv_zk_connector',
        'hr_attendance',
        'hr_holidays',
    ],

    'data': [
        'security/itv_attendance_security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'data/itv_security_scope.xml',
        'data/hr_version_data.xml',
        'data/res_company_data.xml',
        'data/hr_leave_type_data.xml',
        'data/resource_calendar_data.xml',
        'data/attendance_anomaly_type_data.xml',
        'data/attendance_shift_data.xml',
        'views/attendance_anomaly_type_views.xml',
        'views/attendance_shift_views.xml',
        'views/attendance_period_views.xml',
        'wizard/attendance_wizard_views.xml',
        'views/hr_attendance_overtime_line_views.xml',
        'views/attendance_day_views.xml',
        'report/attendance_report.xml',
        'views/hr_attendance_views.xml',
        'views/hr_employee_views.xml',
        'views/zk_terminal_views.xml',
        'views/menus.xml',
    ],
    'demo': [],
    'assets': {},

    'installable': True,
    'application': False,
    'auto_install': False,
}
