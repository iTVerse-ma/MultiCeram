# -*- coding: utf-8 -*-
from odoo import fields, models


class ItvZkPunch(models.Model):
    _inherit = 'itv.zk.punch'

    source = fields.Selection(selection_add=[('cvsecurity', "Lecteur CVSecurity")],
                              ondelete={'cvsecurity': 'cascade'})
    cv_pin = fields.Char("PIN CVSecurity", index='btree_not_null',
                         help="PIN reçu de CVSecurity ; le matricule reste dans « Matricule » comme pour BioTime.")
    cv_key = fields.Char("Identifiant CVSecurity", copy=False, index='btree_not_null',
                         help="Identifiant du passage dans CVSecurity ; à défaut, PIN + heure + lecteur.")

    _cv_uniq = models.UniqueIndex("(backend_id, cv_key) WHERE cv_key IS NOT NULL",
                                  "Ce passage CVSecurity est déjà importé.")
