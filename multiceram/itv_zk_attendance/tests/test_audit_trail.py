# -*- coding: utf-8 -*-
"""Traçabilité : chaque décision laisse qui, quoi et depuis où."""
from odoo.tests import new_test_user
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'itv_zk_attendance')
class TestAuditTrail(TransactionCase):

    def setUp(self):
        super().setUp()
        self.backend = self.env['itv.zk.backend'].create({'name': "BioTime de test", 'url': 'http://biotime.test:8090/'})
        Terminal = self.env['itv.zk.terminal']
        self.entry = Terminal.create({'backend_id': self.backend.id, 'sn': 'A-IN', 'alias': "Entrée",
                                      'usage': 't', 'direction': 'in'})
        self.exit = Terminal.create({'backend_id': self.backend.id, 'sn': 'A-OUT', 'alias': "Sortie",
                                     'usage': 't', 'direction': 'out'})
        self.manager_user = new_test_user(
            self.env, login='audit_n1',
            groups='base.group_user,itv_zk_attendance.group_itv_overtime_validation_1')
        Employee = self.env['hr.employee']
        self.manager = Employee.create({'name': "Chef", 'user_id': self.manager_user.id})
        self.employee = Employee.create({'name': "Employé 200001", 'barcode': '200001',
                                         'itv_schedule_type': 'normal', 'parent_id': self.manager.id})
        self.next_id = 1
        self._punch('2025-11-03 07:58:00', self.entry)
        self._punch('2025-11-03 18:10:00', self.exit)
        self.env['itv.attendance.dirty']._cron_recompute()
        self.day = self.env['itv.attendance.day'].search(
            [('employee_id', '=', self.employee.id), ('date', '=', '2025-11-03')])

    def _punch(self, when, terminal):
        punch = self.env['itv.zk.punch'].create({
            'backend_id': self.backend.id, 'source': 'device', 'biotime_id': self.next_id,
            'emp_code': '200001', 'employee_id': self.employee.id, 'punch_local': when,
            'punch_time': when, 'punch_date': when[:10], 'terminal_id': terminal.id,
        })
        self.next_id += 1
        punch._on_punches_imported()
        return punch

    def _flush_tracking(self):
        """Le suivi des champs est matérialisé juste avant la validation en base."""
        self.env.flush_all()
        self.env.cr.precommit.run()

    def _bodies(self, record):
        return [" ".join((message.body or '').split()) for message in record.message_ids.sorted('id')]

    def test_validation_records_who_what_and_where(self):
        self.day.action_propose_overtime()
        line = self.day.overtime_line_ids
        if 'itv_declaration_state' in line._fields:      # le portail exige une déclaration au préalable
            line._itv_ask_declaration("Combien d'heures ?")
            line.sudo()._itv_portal_declare(line.duration)
        line.with_user(self.manager_user).action_itv_validate_1()

        trace = [body for body in self._bodies(line) if 'Validée N1' in body]
        self.assertTrue(trace, "la validation doit laisser une trace")
        self.assertIn("h détectées", trace[0])
        # Sans requête HTTP (tests, cron), l'origine est explicite.
        self.assertIn("traitement automatique", trace[0])
        self.assertIn(self.manager_user.display_name, trace[0])

    def test_field_changes_are_tracked(self):
        self.entry.usage = 'p'
        self._flush_tracking()
        tracked = self.entry.message_ids.tracking_value_ids
        self.assertIn('Usage', tracked.field_id.mapped('field_description'))

        self.employee.pin = '4321'
        self._flush_tracking()
        values = self.employee.message_ids.tracking_value_ids
        self.assertIn('4321', values.mapped('new_value_char'))

    def test_punch_corrections_are_tracked(self):
        punch = self.env['itv.zk.punch'].search([('employee_id', '=', self.employee.id)], limit=1)
        punch.to_delete = True
        self._flush_tracking()
        self.assertTrue(punch.message_ids.tracking_value_ids,
                        "écarter un pointage doit se voir dans sa discussion")

    def test_anomaly_decisions_are_recorded_on_the_day(self):
        self.day.write({'lg_presence_anomaly': True})
        self.day.invalidate_recordset()
        if 'itv_portal_state' not in self.day._fields:
            self.skipTest("le module portail n'est pas installé")
        self.day._itv_portal_send("Merci d'expliquer cette journée")
        self.day._itv_portal_submit("Panne de voiture")
        self.day.action_itv_portal_accept()
        bodies = " | ".join(self._bodies(self.day))
        for expected in ("Anomalie envoyée à l'employé", "Explication déposée par l'employé", "Explication acceptée"):
            self.assertIn(expected, bodies)
