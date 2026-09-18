# -*- coding: utf-8 -*-
from odoo.modules.neutralize import get_neutralization_queries
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'itv_zk')
class TestNeutralize(TransactionCase):

    def test_neutralized_copy_never_talks_to_production(self):
        backend = self.env['itv.zk.backend'].create({
            'name': "BioTime production",
            'url': 'http://biotime.prod:8090/',
            'read_only': False,
            'token': 'live-token',
        })
        for query in get_neutralization_queries(['itv_zk_connector']):
            self.env.cr.execute(query)
        backend.invalidate_recordset()
        backend = backend.with_context(active_test=False)
        self.assertTrue(backend.read_only)
        self.assertFalse(backend.active)
        self.assertFalse(backend.token)
