# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models

from .zk_sync_state import SYNC_KEYS

LOG_RETENTION_DAYS = 90


class SyncStats:
    """Compteurs d'une exécution de synchronisation, recopiés dans le journal."""

    COUNTERS = ('api_calls', 'fetched', 'created', 'updated', 'unchanged', 'errors')

    def __init__(self):
        for name in self.COUNTERS:
            setattr(self, name, 0)
        self.window_start = None
        self.window_end = None
        self.messages = []
        self.incomplete = False

    def extend_window(self, start, end):
        self.window_start = min(start, self.window_start) if self.window_start else start
        self.window_end = max(end, self.window_end) if self.window_end else end

    def log_vals(self):
        vals = {name: getattr(self, name) for name in self.COUNTERS}
        vals.update(
            window_start=self.window_start or False,
            window_end=self.window_end or False,
            message="\n".join(self.messages) or False,
        )
        return vals


class ItvZkSyncLog(models.Model):
    _name = 'itv.zk.sync.log'
    _description = "Journal de synchronisation BioTime"
    _order = 'id desc'

    backend_id = fields.Many2one('itv.zk.backend', string="Connexion", required=True, ondelete='cascade', index=True)
    key = fields.Selection(SYNC_KEYS, string="Flux", required=True)
    trigger = fields.Selection(
        [('cron', "Planifié"), ('manual', "Manuel")],
        string="Déclencheur", required=True, default='cron')
    status = fields.Selection([
        ('success', "Réussi"),
        ('partial', "Partiel"),
        ('failed', "Échec"),
        ('skipped_locked', "Ignoré (déjà en cours)"),
        ('skipped_down', "Ignoré (BioTime indisponible)"),
    ], string="Résultat", required=True, index=True)
    window_start = fields.Datetime("Début de fenêtre")
    window_end = fields.Datetime("Fin de fenêtre")
    api_calls = fields.Integer("Appels API")
    fetched = fields.Integer("Reçus")
    created = fields.Integer("Créés")
    updated = fields.Integer("Mis à jour")
    unchanged = fields.Integer("Inchangés")
    errors = fields.Integer("Erreurs")
    duration = fields.Float("Durée (s)", digits=(16, 2))
    message = fields.Text("Message")

    @api.autovacuum
    def _gc_sync_logs(self):
        limit = fields.Datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
        self.search([('create_date', '<', limit)]).unlink()
