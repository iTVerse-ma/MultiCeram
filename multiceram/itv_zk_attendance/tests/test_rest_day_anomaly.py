# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'itv_zk_attendance')
class TestRestDayAndAnomalies(TransactionCase):

    def setUp(self):
        super().setUp()
        self.backend = self.env['itv.zk.backend'].create({'name': "BioTime de test", 'url': 'http://biotime.test:8090/'})
        Terminal = self.env['itv.zk.terminal']
        self.entry = Terminal.create({'backend_id': self.backend.id, 'sn': 'T-IN', 'alias': "Entrée", 'usage': 't', 'direction': 'in'})
        self.exit = Terminal.create({'backend_id': self.backend.id, 'sn': 'T-OUT', 'alias': "Sortie", 'usage': 't', 'direction': 'out'})
        self.employee = self.env['hr.employee'].create({'name': "Employé 100001", 'barcode': '100001', 'itv_schedule_type': 'normal'})
        self.Dirty = self.env['itv.attendance.dirty']
        self.rest_type = self.env.ref('itv_zk_attendance.leave_type_rest_day')
        self.next_id = 1

    def _punch(self, when, terminal):
        punch = self.env['itv.zk.punch'].create({
            'backend_id': self.backend.id,
            'source': 'device',
            'biotime_id': self.next_id,
            'emp_code': '100001',
            'employee_id': self.employee.id,
            'punch_local': when,
            'punch_time': when,
            'punch_date': when[:10],
            'terminal_id': terminal.id,
        })
        self.next_id += 1
        punch._on_punches_imported()
        return punch

    def _day(self, date):
        return self.env['itv.attendance.day'].search([('employee_id', '=', self.employee.id), ('date', '=', date)])

    def test_rest_day_is_a_native_leave_shown_in_its_own_column(self):
        self._punch('2025-11-03 07:58:00', self.entry)
        self._punch('2025-11-03 17:02:00', self.exit)
        self.Dirty._cron_recompute()
        wednesday = self._day('2025-11-05')
        wednesday.action_toggle_rest_day()
        leave = self.env['hr.leave'].search([('employee_id', '=', self.employee.id), ('holiday_status_id', '=', self.rest_type.id)])
        self.assertEqual((leave.state, wednesday.is_rest_day), ('validate', True))
        self.assertTrue(self.Dirty.search_count([('employee_id', '=', self.employee.id)]))

        self.Dirty._cron_recompute()
        self.assertEqual((wednesday.is_rest_day, wednesday.has_leave), (True, False))

        wednesday.action_toggle_rest_day()
        self.assertEqual((leave.state, wednesday.is_rest_day), ('cancel', False))
        self.Dirty._cron_recompute()
        self.assertFalse(wednesday.is_rest_day)

    def test_rest_day_outside_the_work_schedule_is_explained(self):
        self._punch('2025-11-03 07:58:00', self.entry)
        self.Dirty._cron_recompute()
        with self.assertRaises(UserError):
            self._day('2025-11-09').action_toggle_rest_day()

    def test_missing_exit_is_fixed_by_a_manual_punch_queued_for_biotime(self):
        self._punch('2025-11-03 07:58:00', self.entry)
        self.Dirty._cron_recompute()
        day = self._day('2025-11-03')
        self.assertEqual((day.anomaly_state, day.lg_detected_present), ('open', True))
        self.assertTrue(day.attendance_ids.itv_is_marker)

        wizard = self.env['itv.attendance.punch.wizard'].create({
            'day_id': day.id, 'punch_time': '2025-11-03 17:05:00', 'punch_state': '2', 'reason': "Oubli de badge",
        })
        wizard.action_confirm()
        punch = self.env['itv.zk.punch'].search([('employee_id', '=', self.employee.id), ('source', '=', 'odoo_manual')])
        self.assertEqual((punch.punch_local, punch.punch_date.isoformat()), ('2025-11-03 18:05:00', '2025-11-03'))
        outbox = self.env['itv.zk.outbox'].search([('res_model', '=', 'itv.zk.punch'), ('res_id', '=', punch.id)])
        self.assertEqual((outbox.operation, outbox.state, outbox.payload['punch_state']), ('manuallog', 'pending', '2'))
        self.assertFalse(day.anomaly_state)
        self.assertEqual(day.attendance_ids.check_out, punch.punch_time)

    def test_justified_anomaly_stays_justified_across_recomputes(self):
        self._punch('2025-11-03 07:58:00', self.entry)
        self.Dirty._cron_recompute()
        day = self._day('2025-11-03')
        wizard = self.env['itv.attendance.anomaly.wizard'].with_context(active_ids=day.ids).create({
            'resolution': 'justified', 'note': "Mission extérieure",
        })
        wizard.action_apply()
        self.assertEqual((day.anomaly_state, day.anomaly_note), ('justified', "Mission extérieure"))

        self.Dirty._enqueue([(self.employee.id, day.date)])
        self.Dirty._cron_recompute()
        self.assertEqual(day.anomaly_state, 'justified')

        day.action_reopen_anomaly()
        self.assertEqual(day.anomaly_state, 'open')

    def test_leave_months_without_punches_create_no_days(self):
        self.env['hr.leave'].create({
            'employee_id': self.employee.id, 'holiday_status_id': self.rest_type.id,
            'request_date_from': '2025-12-03', 'request_date_to': '2025-12-03',
        })
        self.Dirty._cron_recompute()
        self.assertFalse(self.env['itv.attendance.day'].search_count([('employee_id', '=', self.employee.id)]))
