# -*- coding: utf-8 -*-
"""Périmètre « organigramme » réappliqué à chaque mise à jour.

Les règles natives de Présences sont marquées « noupdate » : seul du code peut les corriger.
Et une mise à jour d'un autre module réécrit parfois ses propres règles : rejouer ce réglage
à chaque chargement évite qu'un responsable retrouve silencieusement toutes les présences.
"""
from odoo import api, models

from ..hooks import apply_hierarchy_rules


class IrRule(models.Model):
    _inherit = 'ir.rule'

    @api.model
    def itv_apply_hierarchy_scope(self):
        apply_hierarchy_rules(self.env)
        return True
