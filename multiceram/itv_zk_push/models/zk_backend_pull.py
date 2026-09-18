# -*- coding: utf-8 -*-
"""Reprise du PIN pointeuse lors de la synchronisation BioTime → Odoo.

Le connecteur lit déjà nom et département ; `device_password` (le PIN tapé sur la borne)
n'était pas repris : sans lui, un aller-retour Odoo → BioTime → Odoo perdait le code.
Il alimente le « Code PIN » natif, qui n'accepte que des chiffres.
"""
from odoo import models


class ZkBackend(models.Model):
    _inherit = 'itv.zk.backend'

    def _prepare_employee_vals(self, record, department_ids):
        values = super()._prepare_employee_vals(record, department_ids)
        pin = (record.get('device_password') or '').strip()
        if pin.isdigit():
            values['pin'] = pin
        values['itv_biotime_code'] = (record.get('emp_code') or '').strip() or False
        # Carte enrôlée sur la pointeuse : elle remonte par BioTime.
        values['itv_card_no'] = (record.get('card_no') or '').strip() or False
        return values
