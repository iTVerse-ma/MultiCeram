# -*- coding: utf-8 -*-
"""Recalcule tous les mois employé × mois qui ont des pointages : journées nabi_hr, puis présences et liens HS.

À lancer après une mise à jour de itv_zk_attendance qui change les journées ou le pont vers Présences.
Valide tous les 50 mois ; rejouable. Lancement : conteneur odoo:19 ponctuel (comme 20_parity_legacy.py),
de préférence hors du serveur de dev, qui n'a pas besoin d'être arrêté.
"""
import time

cr = env.cr  # noqa: F821
Day = env['itv.attendance.day']  # noqa: F821
Employee = env['hr.employee'].with_context(active_test=False)  # noqa: F821

cr.execute("SELECT DISTINCT employee_id, date_trunc('month', punch_date)::date FROM itv_zk_punch WHERE employee_id IS NOT NULL ORDER BY 2, 1")
pairs = cr.fetchall()
started = time.monotonic()
for done, (employee_id, month) in enumerate(pairs, start=1):
    Day._recompute_legacy_month(Employee.browse(employee_id), month)
    if done % 50 == 0 or done == len(pairs):
        cr.commit()
        env.invalidate_all()  # noqa: F821
        print("rattrapage : %s/%s mois (%.0f s)" % (done, len(pairs), time.monotonic() - started), flush=True)

cr.execute("SELECT count(*), count(DISTINCT employee_id) FROM hr_attendance WHERE itv_day_id IS NOT NULL")
attendances, employees = cr.fetchone()
cr.execute("SELECT count(*) FROM itv_attendance_day WHERE attendance_conflict")
conflicts = cr.fetchone()[0]
cr.execute("SELECT count(*) FILTER (WHERE itv_state IS NULL), count(itv_state) FROM hr_attendance_overtime_line")
native_lines, circuit_lines = cr.fetchone()
print("rattrapage : %s présences pour %s employés, %s journées en conflit, %s lignes HS natives, %s lignes HS du circuit"
      % (attendances, employees, conflicts, native_lines, circuit_lines), flush=True)
