# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'itv_zk_attendance')
class TestWorkSchedules(TransactionCase):

    def _calendar(self, name):
        return self.env.ref('itv_zk_attendance.resource_calendar_%s' % name)

    def test_nabi_profiles_map_to_native_work_schedules(self):
        Employee = self.env['hr.employee']
        cases = [
            ({'itv_schedule_type': 'poste', 'itv_week_hours': 44}, 'poste'),
            ({'itv_schedule_type': 'securite', 'itv_day_hours': 12}, 'securite'),
            ({'itv_schedule_type': 'normal', 'itv_week_hours': 44}, 'normal_44'),
            ({'itv_schedule_type': 'normal', 'itv_week_hours': 48}, 'normal_48'),
            ({'itv_week_hours': 0}, 'normal_48'),
        ]
        for index, (vals, expected) in enumerate(cases):
            employee = Employee.create(dict(vals, name="Employé %s" % index))
            self.assertEqual(employee.resource_calendar_id, self._calendar(expected), vals)

        without_profile = Employee.create({'name': "Sans réglage"})
        self.assertNotEqual(without_profile.resource_calendar_id, self._calendar('normal_48'))
        without_profile.itv_week_hours = 44
        self.assertEqual(without_profile.resource_calendar_id, self._calendar('normal_44'))

    def test_schedule_hours(self):
        normal = self._calendar('normal_44')
        worked = normal.attendance_ids.filtered(lambda line: line.day_period != 'lunch')
        monday = worked.filtered(lambda line: line.dayofweek == '0')
        saturday = worked.filtered(lambda line: line.dayofweek == '5')
        self.assertEqual((sum(monday.mapped('duration_hours')), sum(saturday.mapped('duration_hours'))), (8.0, 4.0))
        self.assertEqual((normal.hours_per_week, self._calendar('normal_48').hours_per_week), (44.0, 48.0))
        self.assertFalse(normal.attendance_ids.filtered(lambda line: line.dayofweek == '6'))
        self.assertEqual(len(self._calendar('normal_48').attendance_ids.filtered(lambda line: line.day_period != 'lunch').mapped('dayofweek')), 12)
        self.assertEqual((self._calendar('poste').flexible_hours, self._calendar('poste').hours_per_day), (True, 8.0))
        self.assertEqual((self._calendar('securite').flexible_hours, self._calendar('securite').hours_per_day), (True, 12.0))

    def test_poste_profile_allows_a_rest_day_on_sunday(self):
        backend = self.env['itv.zk.backend'].create({'name': "BioTime de test", 'url': 'http://biotime.test:8090/'})
        entry = self.env['itv.zk.terminal'].create({'backend_id': backend.id, 'sn': 'T-IN', 'alias': "Entrée", 'usage': 't', 'direction': 'in'})
        employee = self.env['hr.employee'].create({'name': "Poste 100002", 'barcode': '100002', 'itv_schedule_type': 'poste'})
        self.env['itv.zk.punch'].create({
            'backend_id': backend.id, 'source': 'device', 'biotime_id': 1, 'emp_code': '100002', 'employee_id': employee.id,
            'punch_local': '2025-11-03 06:02:00', 'punch_time': '2025-11-03 06:02:00', 'punch_date': '2025-11-03', 'terminal_id': entry.id,
        })._on_punches_imported()
        self.env['itv.attendance.dirty']._cron_recompute()
        sunday = self.env['itv.attendance.day'].search([('employee_id', '=', employee.id), ('date', '=', '2025-11-09')])
        sunday.action_toggle_rest_day()
        leave = self.env['hr.leave'].search([('employee_id', '=', employee.id)])
        self.assertEqual((leave.state, sunday.is_rest_day), ('validate', True))
