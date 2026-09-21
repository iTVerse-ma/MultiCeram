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
        # Le circuit suit l'organigramme : employé -> chef N1 -> chef N2.
        manager = 'base.group_user,itv_zk_attendance.group_itv_overtime_validation_1'
        self.validator_1 = new_test_user(self.env, login='hs_n1', groups=manager)
        self.validator_2 = new_test_user(self.env, login='hs_n2', groups=manager)
        self.outsider = new_test_user(self.env, login='hs_autre', groups=manager)
        Employee = self.env['hr.employee']
        self.manager_2 = Employee.create({'name': "Chef N2", 'user_id': self.validator_2.id})
        self.manager_1 = Employee.create({'name': "Chef N1", 'user_id': self.validator_1.id, 'parent_id': self.manager_2.id})
        self.employee.parent_id = self.manager_1

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
        self.assertEqual((line.itv_state, line.itv_rate, line.amount_rate, line.status), ('submitted', '25', 1.25, 'to_approve'))
        # 18:00 (départ arrondi) − 08:00 (arrivée arrondie) − norme de 8 h.
        self.assertAlmostEqual(line.duration, 2.0, places=4)
        attendance = self.day.attendance_ids
        attendance.invalidate_recordset()
        self.assertEqual(attendance.linked_overtime_ids, line)
        self.assertAlmostEqual(attendance.overtime_hours, 2.0, places=4)
        self.assertEqual(self.day.overtime_state, 'submitted')

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

    def test_two_level_validation_follows_the_org_chart(self):
        line = self._propose()
        self.assertEqual((line.itv_validator_1_id, line.itv_validator_2_id), (self.validator_1, self.validator_2))
        # Chacun à son tour : le N2 ne fait pas le premier niveau, un tiers ne fait rien.
        with self.assertRaises(AccessError):
            line.with_user(self.validator_2).action_itv_validate_1()
        with self.assertRaises(AccessError):
            line.with_user(self.outsider).action_itv_validate_1()
        with self.assertRaises(AccessError):
            line.with_user(self.validator_1).action_itv_validate_2()
        line.with_user(self.validator_1).action_itv_validate_1()
        with self.assertRaises(AccessError):
            line.with_user(self.validator_1).action_itv_validate_2()
        line.with_user(self.validator_2).action_itv_validate_2()
        self.assertEqual((line.itv_state, line.status), ('validated_2', 'approved'))
        self.assertEqual((line.itv_validated_1_uid, line.itv_validated_2_uid), (self.validator_1, self.validator_2))

        self.Dirty._cron_recompute()
        self.assertAlmostEqual(self.day.lg_total_hs_declare, 2.0, places=4)
        self.assertAlmostEqual(self.day.lg_total_hs25, self.day.lg_hs25_raw + 2.0, places=4)

    def test_an_employee_without_manager_has_nobody_to_validate(self):
        self.employee.parent_id = False
        line = self._propose()
        self.assertFalse(line.itv_validator_1_id)
        for user in (self.validator_1, self.validator_2):
            with self.assertRaises(AccessError):
                line.with_user(user).action_itv_validate_1()

    def test_buttons_are_shown_to_the_person_whose_turn_it_is(self):
        line = self._propose()
        mine = line.with_user(self.validator_1)
        mine.invalidate_recordset()
        self.assertEqual((mine.itv_can_validate_1, mine.itv_can_validate_2), (True, False))
        theirs = line.with_user(self.validator_2)
        theirs.invalidate_recordset()
        self.assertEqual((theirs.itv_can_validate_1, theirs.itv_can_validate_2), (False, False))
        mine.action_itv_validate_1()
        theirs.invalidate_recordset()
        self.assertEqual((theirs.itv_can_validate_1, theirs.itv_can_validate_2), (False, True))

    def test_native_approve_button_follows_the_circuit(self):
        """Le bouton natif de Présences passe par le circuit, donc par l'organigramme."""
        line = self._propose()
        self.employee.attendance_manager_id = self.validator_1
        with self.assertRaises(AccessError):
            self.day.attendance_ids.with_user(self.outsider).action_approve_overtime()
        self.day.attendance_ids.with_user(self.validator_1).action_approve_overtime()
        self.assertEqual(line.itv_state, 'validated_1')

    def test_hours_are_locked_once_validated(self):
        line = self._propose()
        # En circuit, les heures restent modifiables ; l'état, lui, passe par les boutons.
        with self.assertRaises(UserError):
            line.itv_state = 'validated_2'
        line.with_user(self.validator_1).action_itv_validate_1()
        with self.assertRaises(UserError):
            line.duration = 5.0
        line.with_user(self.validator_2).action_itv_reset()
        line.duration = 1.5
        self.assertEqual((line.itv_state, line.duration), ('submitted', 1.5))

    def test_split_line_follows_the_day(self):
        line = self._propose()
        extra = self.env['hr.attendance.overtime.line'].create({
            'employee_id': self.employee.id, 'date': self.day.date, 'duration': 0.5, 'itv_rate': '100',
            'itv_state': 'submitted',
        })
        self.assertEqual((extra.itv_day_id, extra.amount_rate, extra.time_start), (self.day, 2.0, line.time_start))
        self.assertEqual(extra.itv_state, 'submitted')
        self.Dirty._cron_recompute()
        self.assertAlmostEqual(self.day.lg_total_hs100, 0.5, places=4)
        self.assertAlmostEqual(self.day.lg_total_hs_declare, 2.5, places=4)
