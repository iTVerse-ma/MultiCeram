# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrVersion(models.Model):
    _inherit = 'hr.version'

    # Les heures supplémentaires viennent du calcul historique : Présences n'en génère pas.
    ruleset_id = fields.Many2one(default=False)

    @api.model
    def _itv_disable_native_overtime(self):
        versions = self.sudo().with_context(active_test=False, tracking_disable=True).search([('ruleset_id', '!=', False)])
        versions.write({'ruleset_id': False})
        return len(versions)
