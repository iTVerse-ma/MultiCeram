# -*- coding: utf-8 -*-
"""Périmètre de visibilité ramené à l'organigramme.

Les règles natives de Présences donnent « toutes les présences » aux responsables. Elles sont
marquées « noupdate » : un fichier de données ne peut pas les corriger, d'où ce code, appelé à
l'installation et à chaque mise à jour du module.
"""
HIERARCHY_DOMAIN = ("['|', ('employee_id.user_id', '=', user.id), "
                    "('employee_id', 'child_of', user.employee_ids.ids)]")
# Règles ramenées au périmètre « moi et tout ce qui dépend de moi ».
SCOPED_RULES = (
    'hr_attendance.hr_attendance_rule_attendance_admin',
    'hr_attendance.hr_attendance_rule_attendance_manager_restrict',
    'hr_attendance.hr_attendance_overtime_line_rule_admin',
    'hr_attendance.hr_attendance_overtime_line_rule_officer',
    'itv_zk_connector.itv_zk_punch_rule_all',
    'itv_zk_connector.itv_zk_punch_rule_officer',
)


def apply_hierarchy_rules(env):
    for xmlid in SCOPED_RULES:
        rule = env.ref(xmlid, raise_if_not_found=False)
        if rule and rule.domain_force != HIERARCHY_DOMAIN:
            rule.domain_force = HIERARCHY_DOMAIN


def post_init_hook(env):
    apply_hierarchy_rules(env)
