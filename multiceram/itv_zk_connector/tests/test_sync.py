# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields, sql_db
from odoo.tests.common import TransactionCase, tagged

from ..models.zk_backend import SYNC_LOCK_NAMESPACE
from ..services.biotime_client import BioTimeClient
from ..services.timeutils import format_local, utc_to_local
from .common import FakeBioTime

TZ = 'Africa/Casablanca'


@tagged('post_install', '-at_install', 'itv_zk')
class TestBioTimeSync(TransactionCase):

    def setUp(self):
        super().setUp()
        self.server = FakeBioTime()
        self.backend = self.env['itv.zk.backend'].create({
            'name': "BioTime de test",
            'url': 'http://biotime.test:8090/',
            'token': 'fixture-token',
            'timezone': TZ,
        })
        self.employee = self.env['hr.employee'].create({'name': "Employé 100001", 'barcode': '100001'})
        self.env['hr.employee'].create({'name': "Employé 100002", 'barcode': '100002'})
        session = self.server.session

        def fake_client(backend):
            return BioTimeClient(backend.url, token='fixture-token', session=session, sleep=lambda seconds: None)

        self.patch(type(self.env['itv.zk.backend']), '_get_client', fake_client)

    def _punches(self):
        return self.env['itv.zk.punch'].search([('backend_id', '=', self.backend.id)])

    def test_transaction_import_is_idempotent(self):
        logs = [self.backend._run_sync('transactions', trigger='manual') for _run in range(3)]
        self.assertEqual([log.status for log in logs], ['success'] * 3)
        self.assertEqual([log.fetched for log in logs], [3, 3, 3])
        self.assertEqual([log.created for log in logs], [3, 0, 0])
        punches = self._punches()
        self.assertEqual(len(punches), 3)

        first = punches.filtered(lambda punch: punch.biotime_id == 1001)
        self.assertEqual(first.employee_id, self.employee)
        self.assertEqual(first.punch_local, '2026-09-10 06:02:11')
        self.assertEqual(first.punch_time, fields.Datetime.to_datetime('2026-09-10 05:02:11'))
        self.assertEqual(first.punch_date, fields.Date.to_date('2026-09-10'))

        late = punches.filtered(lambda punch: punch.biotime_id == 1002)
        self.assertGreater(late.upload_delay_min, 24 * 60)

        unknown = punches.filtered(lambda punch: punch.biotime_id == 1003)
        self.assertFalse(unknown.employee_id)
        self.assertEqual(unknown.terminal_id.usage, 'unclassified')
        self.assertTrue(self.env['itv.zk.sync.state']._get(self.backend, 'transactions').watermark)

    def test_terminal_back_online_triggers_a_targeted_backfill(self):
        now_local = format_local(utc_to_local(fields.Datetime.now(), TZ))
        self.server.terminals['data'][0]['last_activity'] = now_local
        first = self.backend._run_sync('terminals')
        self.assertEqual((first.status, first.created), ('success', 2))
        Terminal = self.env['itv.zk.terminal']
        restaurant = Terminal.search([('sn', '=', 'PYAFIX00000002')])
        self.assertTrue(restaurant.offline_since)
        self.assertFalse(Terminal.search([('sn', '=', 'VDEFIX00000001')]).offline_since)

        self.server.terminals['data'][1]['last_activity'] = now_local
        self.backend._run_sync('terminals')
        backfill_calls = [call for call in self.server.session.calls if call['params'].get('terminal_sn') == 'PYAFIX00000002']
        self.assertTrue(backfill_calls)
        self.assertFalse(restaurant.offline_since)
        self.assertEqual(len(self._punches()), 3)

    def test_employee_sync_maps_departments_and_skips_unchanged(self):
        users_before = self.env['res.users'].search_count([])
        first = self.backend._run_sync('employees')
        self.assertEqual(first.status, 'success')
        self.assertEqual((first.fetched, first.created, first.updated), (2, 1, 1))

        created = self.env['hr.employee'].search([('barcode', '=', '100003')])
        self.assertTrue(created.itv_to_complete)
        self.assertEqual(created.department_id.name, "Émaillage")
        self.assertEqual(created.department_id.parent_id.name, "Production")
        self.assertEqual(self.employee.itv_biotime_emp_id, 5)

        second = self.backend._run_sync('employees')
        self.assertEqual((second.unchanged, second.updated, second.created), (2, 0, 0))
        self.assertEqual(self.env['res.users'].search_count([]), users_before)

    def test_concurrent_run_is_skipped(self):
        state = self.env['itv.zk.sync.state']._get(self.backend, 'transactions')
        other = sql_db.db_connect(self.env.cr.dbname).cursor()
        try:
            other.execute("SELECT pg_advisory_xact_lock(%s, %s)", (SYNC_LOCK_NAMESPACE, state.id))
            log = self.backend._run_sync('transactions')
        finally:
            other.rollback()
            other.close()
        self.assertEqual(log.status, 'skipped_locked')
        self.assertFalse(self._punches())

    def test_circuit_breaker_opens_after_three_failures(self):
        self.server.down = True
        statuses = [self.backend._run_sync('transactions').status for _run in range(3)]
        self.assertEqual(statuses, ['failed'] * 3)
        self.assertEqual(self.backend.status, 'down')
        self.assertEqual(self.backend._run_sync('transactions').status, 'skipped_down')

        # La sonde des terminaux tourne malgré le circuit ouvert et le referme quand BioTime répond.
        self.server.down = False
        self.assertEqual(self.backend._run_sync('terminals').status, 'success')
        self.assertEqual(self.backend.status, 'ok')

    def test_reconcile_reimports_only_days_with_missing_punches(self):
        today = utc_to_local(fields.Datetime.now(), TZ).date()
        missing_day = today - timedelta(days=2)
        self.server.day_counts = {str(missing_day): 3}
        self.backend.reconcile_days = 5

        log = self.backend._run_sync('reconcile')
        self.assertEqual(log.status, 'success')
        calls = self.server.session.calls
        self.assertEqual(len([call for call in calls if call['params'].get('page_size') == 1]), 5)
        refetch = [call for call in calls
                   if call['params'].get('start_time') == '%s 00:00:00' % missing_day and call['params'].get('page_size') != 1]
        self.assertTrue(refetch)
        self.assertIn(str(missing_day), log.message)
