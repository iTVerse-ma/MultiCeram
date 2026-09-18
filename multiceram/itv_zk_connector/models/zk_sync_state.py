# -*- coding: utf-8 -*-
from odoo import api, fields, models

SYNC_KEYS = [
    ('transactions', "Pointages"),
    ('terminals', "Terminaux"),
    ('employees', "Employés et départements"),
    ('reconcile', "Réconciliation des pointages"),
]


class ItvZkSyncState(models.Model):
    _name = 'itv.zk.sync.state'
    _description = "État de synchronisation BioTime"
    _order = 'backend_id, key'

    backend_id = fields.Many2one('itv.zk.backend', string="Connexion", required=True, ondelete='cascade', index=True)
    key = fields.Selection(SYNC_KEYS, string="Flux", required=True)
    watermark = fields.Datetime("Filigrane", help="Fin de la dernière fenêtre importée entièrement (UTC).")
    cursor = fields.Json("Curseur")
    last_success = fields.Datetime("Dernier succès")

    _backend_key_uniq = models.UniqueIndex('(backend_id, key)', "Un seul état par flux et par connexion.")

    @api.model
    def _get(self, backend, key):
        state = self.search([('backend_id', '=', backend.id), ('key', '=', key)], limit=1)
        return state or self.create({'backend_id': backend.id, 'key': key})
