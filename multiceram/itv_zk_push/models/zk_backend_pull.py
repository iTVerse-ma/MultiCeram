# -*- coding: utf-8 -*-
"""Reprise du PIN pointeuse lors de la synchronisation BioTime → Odoo.

Le connecteur lit déjà nom et département ; `device_password` (le PIN tapé sur la borne)
n'était pas repris : sans lui, un aller-retour Odoo → BioTime → Odoo perdait le code.
"""
from odoo import models


class ZkBackend(models.Model):
    _inherit = 'itv.zk.backend'

    def _prepare_employee_vals(self, record, department_ids):
        values = super()._prepare_employee_vals(record, department_ids)
        pin = (record.get('device_password') or '').strip()
        if pin:
            values['itv_biotime_pin'] = pin
        return values
