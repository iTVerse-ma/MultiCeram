# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'itv_zk_attendance')
class TestAttendanceReports(TransactionCase):

    def setUp(self):
        super().setUp()
        self.backend = self.env['itv.zk.backend'].create({'name': "BioTime de test", 'url': 'http://biotime.test:8090/'})
        Terminal = self.env['itv.zk.terminal']
        self.entry = Terminal.create({'backend_id': self.backend.id, 'sn': 'T-IN', 'alias': "Entrée", 'usage': 't', 'direction': 'in'})
        self.exit = Terminal.create({'backend_id': self.backend.id, 'sn': 'T-OUT', 'alias': "Sortie", 'usage': 't', 'direction': 'out'})
        self.employee = self.env['hr.employee'].create({'name': "Employé 100001", 'barcode': '100001', 'itv_schedule_type': 'normal'})
        self.next_id = 1
        self._punch('2025-11-03 07:58:00', self.entry)
        self._punch('2025-11-03 18:10:00', self.exit)
        self._punch('2025-11-04 22:04:00', self.entry)
        self._punch('2025-11-05 06:01:00', self.exit)
        self._punch('2025-11-06 07:55:00', self.entry)
        self.env['itv.attendance.dirty']._cron_recompute()
        self.days = self.env['itv.attendance.day'].search([('employee_id', '=', self.employee.id)])

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
        return self.days.filtered(lambda day: str(day.date) == date)

    def test_punch_summary_and_anomaly_label(self):
        self.assertEqual(self._day('2025-11-03').punch_summary, "07:58 → 18:10 (2)")
        self.assertEqual(self._day('2025-11-04').punch_summary, "22:04 → 06:01 J+1 (2)")
        self.assertFalse(self._day('2025-11-05').punch_summary)
        thursday = self._day('2025-11-06')
        self.assertEqual((thursday.punch_summary, thursday.anomaly_label), ("— (1)", "Détecté présent"))
        self.assertFalse(self._day('2025-11-03').anomaly_label)

    def test_monthly_report_has_one_page_per_employee_and_month(self):
        pages = self.days._report_pages()
        self.assertEqual(len(pages), 1)
        self.assertEqual((pages[0]['totals']['days'], pages[0]['totals']['lg_worked_day']), (30, 3))
        html = self.env['ir.actions.report']._render_qweb_html('itv_zk_attendance.action_report_attendance_month', self.days.ids)[0].decode()
        self.assertIn("Employé 100001", html)
        self.assertIn("07:58 → 18:10 (2)", html)
        self.assertIn("30 jours", html)
