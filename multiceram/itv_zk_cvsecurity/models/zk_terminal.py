# -*- coding: utf-8 -*-
from odoo import api, models


class ItvZkTerminal(models.Model):
    _inherit = 'itv.zk.terminal'

    @api.model
    def _itv_guess_direction(self, name):
        """Règle de l'ancien connecteur : « Hors » = sortie, « En » = entrée ; sinon, sans sens."""
        lowered = (name or '').lower()
        if 'hors' in lowered or 'sortie' in lowered or 'exit' in lowered:
            return 'out'
        if lowered.startswith('en ') or ' en ' in lowered or 'entr' in lowered or 'entry' in lowered:
            return 'in'
        return 'none'
