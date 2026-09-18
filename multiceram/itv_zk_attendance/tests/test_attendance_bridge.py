# -*- coding: utf-8 -*-
from datetime import date, datetime

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'itv_zk_attendance')
class TestAttendanceBridge(TransactionCase):

    def setUp(self):
        super().setUp()
        self.backend = self.env['itv.zk.backend'].create({'name': "BioTime de test", 'url': 'http://biotime.test:8090/'})
        Terminal = self.env['itv.zk.terminal']
        self.entry = Terminal.create({'backend_id': self.backend.id, 'sn': 'T-IN', 'alias': "Entrée", 'usage': 't', 'direction': 'in'})
        self.exit = Terminal.create({'backend_id': self.backend.id, 'sn': 'T-OUT', 'alias': "Sortie", 'usage': 't', 'direction': 'out'})
        self.employee = self.env['hr.employee'].create({'name': "Employé 100001", 'barcode': '100001', 'itv_schedule_type': 'normal'})
        self.Attendance = self.env['hr.attendance']
        self.Dirty = self.env['itv.attendance.dirty']
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

    def _day(self, day):
        self.Dirty._cron_recompute()
        return self.env['itv.attendance.day'].search([('employee_id', '=', self.employee.id), ('date', '=', day)])

    def test_worked_day_becomes_one_attendance_without_native_overtime(self):
        arrival = self._punch('2025-11-03 07:58:00', self.entry)
        departure = self._punch('2025-11-03 18:10:00', self.exit)
        attendance = self._day('2025-11-03').attendance_ids
        self.assertEqual(len(attendance), 1)
        self.assertEqual((attendance.check_in, attendance.check_out), (arrival.punch_time, departure.punch_time))
        self.assertEqual((attendance.in_mode, attendance.itv_is_marker), ('technical', False))
        # 2 h 10 d'heures supplémentaires dans le calcul historique, aucune générée par Présences.
        self.assertAlmostEqual(attendance.itv_hs, 2 + 10 / 60, places=4)
        self.assertFalse(self.employee.sudo().version_id.ruleset_id)
        self.assertFalse(self.env['hr.attendance.overtime.line'].search_count([('employee_id', '=', self.employee.id)]))

    def test_day_without_a_clean_pair_keeps_a_marker_line(self):
        self._punch('2025-11-03 07:58:00', self.entry)
        marker = self._day('2025-11-03').attendance_ids
        self.assertEqual((len(marker), marker.itv_is_marker), (1, True))
        self.assertEqual(marker.check_out - marker.check_in, datetime(2025, 11, 3, 12, 0, 1) - datetime(2025, 11, 3, 12, 0, 0))

        self._punch('2025-11-03 17:02:00', self.exit)
        attendance = self._day('2025-11-03').attendance_ids
        self.assertEqual((len(attendance), attendance.itv_is_marker), (1, False))

    def test_every_day_of_the_month_has_a_line(self):
        self._punch('2025-11-03 07:58:00', self.entry)
        self._punch('2025-11-03 18:10:00', self.exit)
        self.Dirty._cron_recompute()
        attendances = self.Attendance.search([('employee_id', '=', self.employee.id)])
        self.assertEqual(len(attendances), 30)
        self.assertEqual(len(attendances.filtered('itv_is_marker')), 29)

    def test_punch_corrections_rebuild_the_attendance(self):
        arrival = self._punch('2025-11-03 07:58:00', self.entry)
        wrong_exit = self._punch('2025-11-03 12:01:00', self.exit)
        self.assertEqual(self._day('2025-11-03').attendance_ids.check_out, wrong_exit.punch_time)

        wrong_exit.to_delete = True
        real_exit = self._punch('2025-11-03 17:05:00', self.exit)
        attendance = self._day('2025-11-03').attendance_ids
        self.assertEqual((len(attendance), attendance.check_out), (1, real_exit.punch_time))

        arrival.to_delete = True
        self.assertTrue(self._day('2025-11-03').attendance_ids.itv_is_marker)

    def test_night_shift_stays_on_the_evening_day(self):
        evening = self._punch('2025-11-03 22:04:00', self.entry)
        morning = self._punch('2025-11-04 06:01:00', self.exit)
        attendance = self._day('2025-11-03').attendance_ids
        self.assertEqual((attendance.check_in, attendance.check_out), (evening.punch_time, morning.punch_time))
        self.assertTrue(self._day('2025-11-04').attendance_ids.itv_is_marker)

    def test_overlap_with_a_manual_attendance_is_reported_on_the_day(self):
        manual = self.Attendance.create({
            'employee_id': self.employee.id, 'check_in': datetime(2025, 11, 3, 9, 0), 'check_out': datetime(2025, 11, 3, 10, 0),
        })
        self._punch('2025-11-03 07:58:00', self.entry)
        self._punch('2025-11-03 17:05:00', self.exit)
        day = self._day('2025-11-03')
        self.assertTrue(day.attendance_conflict)
        self.assertFalse(day.attendance_ids)

        manual.unlink()
        self.Dirty._enqueue([(self.employee.id, date(2025, 11, 3))])
        day = self._day('2025-11-03')
        self.assertFalse(day.attendance_conflict)
        self.assertEqual(len(day.attendance_ids), 1)
