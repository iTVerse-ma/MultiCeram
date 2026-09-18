# -*- coding: utf-8 -*-
from odoo import fields, models

LEGACY_TERMINAL_FIELDS = {'itv_legacy_presence', 'usage', 'direction', 'is_uhf_bridge'}


class ItvZkTerminal(models.Model):
    _inherit = 'itv.zk.terminal'

    itv_legacy_presence = fields.Boolean(
        "Présence dans le calcul historique",
        help="Ses pointages comptent comme présence dans le calcul historique nabi_hr, comme les pointages "
             "sans terminal de l'ancien module. Coché sur le Magasin, dont les pointages de novembre 2025 "
             "étaient comptés ainsi.")

    def write(self, vals):
        result = super().write(vals)
        if LEGACY_TERMINAL_FIELDS & set(vals) and not self.env.context.get('itv_skip_legacy_enqueue'):
            self.env['itv.attendance.dirty']._enqueue_from_punches(terminal_ids=self.ids)
        return result
