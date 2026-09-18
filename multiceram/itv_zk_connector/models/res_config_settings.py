# -*- coding: utf-8 -*-
"""Cadence de la synchronisation des pointages, choisie parmi deux modes.

Un mode règle d'un coup les tâches planifiées, la fenêtre de relecture des connexions et le
recalcul immédiat : pas de réglages chiffrés qui pourraient se contredire.
"""
from datetime import timedelta

from odoo import api, fields, models

SYNC_MODE_PARAM = 'itv_zk_connector.sync_mode'
SYNC_MODES = [
    ('instant', "Instantané (≈ 1 min)"),
    ('standard', "Standard (≈ 15 min)"),
]
# Import des pointages et des employés (min), relecture (min), recalcul dès l'import.
# Standard à l'installation ; Instantané se choisit dans les paramètres.
DEFAULT_SYNC_MODE = 'standard'
SYNC_PRESETS = {
    'instant': {'transactions': 1, 'employees': 5, 'overlap': 10, 'immediate': True},
    'standard': {'transactions': 5, 'employees': 60, 'overlap': 30, 'immediate': False},
}
PRESET_CRONS = {
    'transactions': 'itv_zk_connector.ir_cron_itv_zk_transactions',
    'employees': 'itv_zk_connector.ir_cron_itv_zk_employees',
}


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    itv_zk_sync_mode = fields.Selection(
        SYNC_MODES, string="Synchronisation des pointages", default=DEFAULT_SYNC_MODE,
        config_parameter=SYNC_MODE_PARAM,
        help="Instantané : import chaque minute et recalcul des journées dès l'arrivée des pointages. "
             "Reste léger même pour un millier d'employés (un appel à BioTime par minute, seules les "
             "journées touchées sont recalculées). Un employé créé sur la pointeuse arrive avec les pointages ; "
             "ses modifications suivent toutes les 5 minutes.\n"
             "Standard : import toutes les 5 minutes, journées recalculées par la tâche de 10 minutes. "
             "Un employé créé sur la pointeuse arrive avec les pointages ; ses modifications suivent toutes les heures.")

    def set_values(self):
        super().set_values()
        self.env['itv.zk.backend']._itv_apply_sync_mode(self.itv_zk_sync_mode or DEFAULT_SYNC_MODE)


class ItvZkBackend(models.Model):
    _inherit = 'itv.zk.backend'

    @api.model
    def _itv_sync_mode(self):
        return self.env['ir.config_parameter'].sudo().get_param(SYNC_MODE_PARAM, DEFAULT_SYNC_MODE)

    @api.model
    def _itv_apply_sync_mode(self, mode):
        preset = SYNC_PRESETS[mode]
        for key, xmlid in PRESET_CRONS.items():
            cron = self.env.ref(xmlid, raise_if_not_found=False)
            if not cron:
                continue
            cron = cron.sudo()
            minutes = preset[key]
            if cron.interval_type != 'minutes' or cron.interval_number != minutes:
                vals = {'interval_number': minutes, 'interval_type': 'minutes'}
                # Sinon la nouvelle cadence n'agit qu'après le prochain passage prévu à l'ancienne.
                soon = fields.Datetime.now() + timedelta(minutes=minutes)
                if cron.nextcall > soon:
                    vals['nextcall'] = soon
                cron.write(vals)
        self.sudo().with_context(active_test=False).search([]).write({'overlap_minutes': preset['overlap']})

    @api.model
    def _itv_recompute_immediately(self):
        return SYNC_PRESETS.get(self._itv_sync_mode(), SYNC_PRESETS[DEFAULT_SYNC_MODE])['immediate']
