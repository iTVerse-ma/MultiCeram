# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import new_test_user
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'itv_zk_attendance')
class TestOvertimeCircuit(TransactionCase):

    def setUp(self):
        super().setUp()
        self.backend = self.env['itv.zk.backend'].create({'name': "BioTime de test", 'url': 'http://biotime.test:8090/'})
        Terminal = self.env['itv.zk.terminal']
        self.entry = Terminal.create({'backend_id': self.backend.id, 'sn': 'T-IN', 'alias': "Entrée", 'usage': 't', 'direction': 'in'})
        self.exit = Terminal.create({'backend_id': self.backend.id, 'sn': 'T-OUT', 'alias': "Sortie", 'usage': 't', 'direction': 'out'})
        self.employee = self.env['hr.employee'].create({'name': "Employé 100001", 'barcode': '100001', 'itv_schedule_type': 'normal'})
        self.Dirty = self.env['itv.attendance.dirty']
        self.next_id = 1
        self._punch('2025-11-03 07:58:00', self.entry)
        self.departure = self._punch('2025-11-03 18:10:00', self.exit)
        self.Dirty._cron_recompute()
        self.day = self.env['itv.attendance.day'].search([('employee_id', '=', self.employee.id), ('date', '=', '2025-11-03')])
        level_1 = 'base.group_user,itv_zk_attendance.group_itv_overtime_validation_1'
        level_2 = 'base.group_user,itv_zk_attendance.group_itv_overtime_validation_2'
        self.validator_1 = new_test_user(self.env, login='hs_n1', groups=level_1)
        self.validator_2 = new_test_user(self.env, login='hs_n2', groups=level_2)
        self.other_validator_2 = new_test_user(self.env, login='hs_n2_bis', groups=level_2)

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

    def _propose(self):
        self.day.action_propose_overtime()
        return self.day.overtime_line_ids

    def test_proposal_is_shown_on_the_native_attendance(self):
        line = self._propose()
        self.assertEqual((line.itv_state, line.itv_rate, line.amount_rate, line.status), ('draft', '25', 1.25, 'to_approve'))
        # 18:00 (départ arrondi) − 08:00 (arrivée arrondie) − norme de 8 h.
        self.assertAlmostEqual(line.duration, 2.0, places=4)
        attendance = self.day.attendance_ids
        attendance.invalidate_recordset()
        self.assertEqual(attendance.linked_overtime_ids, line)
        self.assertAlmostEqual(attendance.overtime_hours, 2.0, places=4)
        self.assertEqual(self.day.overtime_state, 'draft')

    def test_rebuilding_the_attendance_keeps_the_overtime(self):
        line = self._propose()
        self.departure.to_delete = True
        later = self._punch('2025-11-03 19:02:00', self.exit)
        self.Dirty._cron_recompute()
        attendance = self.day.attendance_ids
        self.assertEqual(attendance.check_out, later.punch_time)
        self.assertTrue(line.exists())
        self.assertEqual((line.time_start, line.time_stop), (attendance.check_in, attendance.check_out))
        attendance.invalidate_recordset()
        self.assertEqual(attendance.linked_overtime_ids, line)

    def test_two_level_validation_by_two_different_people(self):
        line = self._propose()
        line.action_itv_submit()
        with self.assertRaises(AccessError):
            line.with_user(self.validator_1).action_itv_validate_2()
        line.with_user(self.validator_2).action_itv_validate_1()
        with self.assertRaises(UserError):
            line.with_user(self.validator_2).action_itv_validate_2()
        line.with_user(self.other_validator_2).action_itv_validate_2()
        self.assertEqual((line.itv_state, line.status), ('validated_2', 'approved'))
        self.assertEqual((line.itv_validated_1_uid, line.itv_validated_2_uid), (self.validator_2, self.other_validator_2))

        self.Dirty._cron_recompute()
        self.assertAlmostEqual(self.day.lg_total_hs_declare, 2.0, places=4)
        self.assertAlmostEqual(self.day.lg_total_hs25, self.day.lg_hs25_raw + 2.0, places=4)

    def test_native_approve_button_follows_the_circuit(self):
        line = self._propose()
        self.employee.attendance_manager_id = self.validator_2
        attendance = self.day.attendance_ids.with_user(self.validator_2)
        with self.assertRaises(UserError):
            attendance.action_approve_overtime()
        line.action_itv_submit()
        attendance.invalidate_recordset()
        attendance.action_approve_overtime()
        self.assertEqual(line.itv_state, 'validated_1')

    def test_hours_are_locked_once_in_the_circuit(self):
        line = self._propose()
        line.action_itv_submit()
        with self.assertRaises(UserError):
            line.duration = 5.0
        with self.assertRaises(UserError):
            line.itv_state = 'validated_2'
        line.action_itv_reset()
        line.duration = 1.5
        self.assertEqual((line.itv_state, line.duration), ('draft', 1.5))

    def test_split_line_follows_the_day(self):
        line = self._propose()
        extra = self.env['hr.attendance.overtime.line'].with_context(default_itv_state='draft').create({
            'employee_id': self.employee.id, 'date': self.day.date, 'duration': 0.5, 'itv_rate': '100',
        })
        self.assertEqual((extra.itv_day_id, extra.amount_rate, extra.time_start), (self.day, 2.0, line.time_start))
        line.action_itv_submit()
        self.assertEqual(extra.itv_state, 'submitted')
        self.Dirty._cron_recompute()
        self.assertAlmostEqual(self.day.lg_total_hs100, 0.5, places=4)
        self.assertAlmostEqual(self.day.lg_total_hs_declare, 2.5, places=4)
