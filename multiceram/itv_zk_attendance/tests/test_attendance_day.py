# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'itv_zk_attendance')
class TestLegacyRecompute(TransactionCase):

    def setUp(self):
        super().setUp()
        self.backend = self.env['itv.zk.backend'].create({'name': "BioTime de test", 'url': 'http://biotime.test:8090/'})
        Terminal = self.env['itv.zk.terminal']
        self.entry = Terminal.create({'backend_id': self.backend.id, 'sn': 'T-IN', 'alias': "Entrée", 'usage': 't', 'direction': 'in'})
        self.exit = Terminal.create({'backend_id': self.backend.id, 'sn': 'T-OUT', 'alias': "Sortie", 'usage': 't', 'direction': 'out'})
        self.employee = self.env['hr.employee'].create({'name': "Employé 100001", 'barcode': '100001', 'itv_schedule_type': 'normal'})
        self.Dirty = self.env['itv.attendance.dirty']
        self.Day = self.env['itv.attendance.day']
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
        return punch

    def test_imported_punches_are_recomputed_into_days(self):
        punches = self._punch('2025-11-03 07:58:00', self.entry) | self._punch('2025-11-03 18:10:00', self.exit)
        punches._on_punches_imported()
        self.assertEqual(self.Dirty.search_count([('employee_id', '=', self.employee.id)]), 1)

        self.Dirty._cron_recompute()
        days = self.Day.search([('employee_id', '=', self.employee.id)])
        self.assertEqual(len(days), 30)
        monday = days.filtered(lambda day: day.date == date(2025, 11, 3))
        # 18:10 − 08:00 (arrivée arrondie), sans pause : 10 h 10 de présence, 2 h 10 au-delà de la norme.
        self.assertAlmostEqual(monday.lg_heures, 10 + 10 / 60, places=4)
        self.assertAlmostEqual(monday.lg_hs, 2 + 10 / 60, places=4)
        self.assertEqual((monday.weekday, monday.lg_worked_day), ('0', 1))
        self.assertEqual(sum(days.mapped('lg_absent_day')), 29)
        self.assertFalse(self.Dirty.search_count([]))

    def test_terminal_counted_as_presence_in_the_legacy_calculation(self):
        magasin = self.env['itv.zk.terminal'].create({
            'backend_id': self.backend.id, 'sn': 'MAG', 'alias': "Magasin", 'usage': 'm', 'itv_legacy_presence': True,
        })
        (self._punch('2025-11-03 08:00:00', magasin) | self._punch('2025-11-03 17:00:00', magasin))._on_punches_imported()
        self.Dirty._cron_recompute()
        monday = self.Day.search([('employee_id', '=', self.employee.id), ('date', '=', '2025-11-03')])
        self.assertAlmostEqual(monday.lg_heures, 9.0, places=4)
        self.assertFalse(monday.lg_detected_present)

        self.Dirty.search([]).unlink()
        magasin.itv_legacy_presence = False
        self.assertEqual(self.Dirty.search_count([('employee_id', '=', self.employee.id)]), 1)
        self.Dirty._cron_recompute()
        self.assertTrue(monday.lg_detected_present)
        # Règle d'origine : sans anomalie de présence impaire, les heures se calculent sur les pointages
        # retenus de tout usage, même sans aucun pointage de présence.
        self.assertAlmostEqual(monday.lg_heures, 9.0, places=4)

    def test_raw_punch_correction_requeues_the_month(self):
        punch = self._punch('2025-11-03 07:58:00', self.entry)
        self.Dirty.search([]).unlink()
        punch.duplicate = True
        self.assertEqual(self.Dirty.search_count([('employee_id', '=', self.employee.id)]), 1)

    def test_month_where_the_original_page_crashed_is_flagged(self):
        (self._punch('2025-11-03 23:46:00', self.entry) | self._punch('2025-11-03 23:59:00', self.exit))._on_punches_imported()
        self.Dirty._cron_recompute()
        days = self.Day.search([('employee_id', '=', self.employee.id)])
        self.assertEqual(set(days.mapped('lg_error')), {'round_overflow'})
        self.assertFalse(sum(days.mapped('lg_heures')))
