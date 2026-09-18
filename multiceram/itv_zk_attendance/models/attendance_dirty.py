# -*- coding: utf-8 -*-
from datetime import timedelta

from psycopg2.extras import execute_values

from odoo import api, fields, models

RECOMPUTE_BATCH = 200
# Au-delà, le mois entier coûte moins cher que les journées une par une.
FULL_MONTH_THRESHOLD = 5


class ItvAttendanceDirty(models.Model):
    _name = 'itv.attendance.dirty'
    _description = "Journées de pointage à recalculer"
    _order = 'id'

    employee_id = fields.Many2one('hr.employee', string="Employé", required=True, ondelete='cascade')
    day = fields.Date("Jour", required=True)

    _employee_day_uniq = models.UniqueIndex('(employee_id, day)')

    def init(self):
        # La file portait le mois avant le recalcul par journée (colonne obligatoire, devenue inutile).
        self.env.cr.execute("ALTER TABLE itv_attendance_dirty DROP COLUMN IF EXISTS month")

    @api.model
    def _enqueue(self, pairs):
        """Met en file des couples (employé, jour)."""
        rows = {(employee_id, day) for employee_id, day in pairs if employee_id and day}
        if not rows:
            return 0
        now, uid = fields.Datetime.now(), self.env.uid
        execute_values(
            self.env.cr,
            "INSERT INTO itv_attendance_dirty (employee_id, day, create_uid, write_uid, create_date, write_date) "
            "VALUES %s ON CONFLICT DO NOTHING",
            [(employee_id, day, uid, uid, now, now) for employee_id, day in rows],
        )
        return self.env.cr.rowcount

    @api.model
    def _enqueue_from_punches(self, employee_ids=None, terminal_ids=None, month=None):
        """Met en file les journées qui ont des pointages : toutes, ou celles des employés / terminaux / mois indiqués."""
        query = """
            INSERT INTO itv_attendance_dirty (employee_id, day, create_uid, write_uid, create_date, write_date)
            SELECT DISTINCT employee_id, punch_date, %(uid)s, %(uid)s, %(now)s, %(now)s
              FROM itv_zk_punch
             WHERE employee_id IS NOT NULL {employees} {terminals} {month}
            ON CONFLICT DO NOTHING
        """.format(
            employees="AND employee_id = ANY(%(employees)s)" if employee_ids is not None else "",
            terminals="AND terminal_id = ANY(%(terminals)s)" if terminal_ids is not None else "",
            month="AND date_trunc('month', punch_date) = %(month)s" if month else "",
        )
        self.env.cr.execute(query, {
            'uid': self.env.uid, 'now': fields.Datetime.now(),
            'employees': list(employee_ids or []), 'terminals': list(terminal_ids or []), 'month': month,
        })
        return self.env.cr.rowcount

    @api.model
    def _cron_recompute(self):
        Day = self.env['itv.attendance.day']
        processed = 0
        while True:
            batch = self.search([], limit=RECOMPUTE_BATCH)
            if not batch:
                return processed
            for employee, items in batch.grouped('employee_id').items():
                Day._recompute_days(employee, items.mapped('day'), full_month_threshold=FULL_MONTH_THRESHOLD)
            processed += len(batch)
            batch.unlink()
            if self.env.context.get('cron_id'):
                remaining_time = self.env['ir.cron']._commit_progress(len(batch), remaining=self.search_count([]))
                if remaining_time < 60:
                    return processed

    @api.model
    def _cron_close_yesterday(self):
        """Chaque matin : la journée de la veille pour tous les employés, même sans pointage.

        Sans cela, une journée entièrement absente n'aurait aucune ligne : l'absence ne serait pas comptée.
        """
        yesterday = fields.Date.context_today(self) - timedelta(days=1)
        employees = self.env['hr.employee'].sudo().search([])
        self._enqueue([(employee_id, yesterday) for employee_id in employees.ids])
        return self._cron_recompute()
