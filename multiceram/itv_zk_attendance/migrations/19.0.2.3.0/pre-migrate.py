# -*- coding: utf-8 -*-
"""Les postes deviennent des horaires de travail Odoo ordinaires.

Le modèle maison `itv.attendance.shift` disparaît : le planning et les journées pointent
désormais vers `resource.calendar`. Les colonnes de l'ancien lien sont retirées pour que
les nouvelles soient créées proprement.
"""


def migrate(cr, version):
    cr.execute("ALTER TABLE itv_employee_shift DROP COLUMN IF EXISTS shift_id")
    cr.execute("ALTER TABLE itv_attendance_day DROP COLUMN IF EXISTS itv_shift_id")
    cr.execute("ALTER TABLE hr_employee DROP COLUMN IF EXISTS itv_shift_id")
    cr.execute("DELETE FROM ir_model_data WHERE model = 'itv.attendance.shift'")
    cr.execute("DELETE FROM ir_model_data WHERE module = 'itv_zk_attendance' AND name LIKE 'itv_shift_%'")
