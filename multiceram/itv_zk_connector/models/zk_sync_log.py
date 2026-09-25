# -*- coding: utf-8 -*-
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models

from .zk_sync_state import SYNC_KEYS

LOG_RETENTION_DAYS = 90
# Au-delà, le détail devient illisible : on garde les premières lignes et on compte le reste.
DETAIL_LIMIT = 40
# Ce que chaque flux lit dans BioTime, au singulier et au pluriel : « 7 employés lus », « 1 terminal lu ».
FLOW_SUBJECTS = {
    'transactions': ("pointage", "pointages"),
    'terminals': ("terminal", "terminaux"),
    'employees': ("employé", "employés"),
    'reconcile': ("journée comparée", "journées comparées"),
}


class SyncStats:
    """Compteurs d'une exécution de synchronisation, recopiés dans le journal."""

    COUNTERS = ('api_calls', 'fetched', 'created', 'updated', 'unchanged', 'errors')

    def __init__(self):
        for name in self.COUNTERS:
            setattr(self, name, 0)
        self.window_start = None
        self.window_end = None
        self.messages = []
        self.details = []
        self.detail_overflow = 0
        self.incomplete = False

    def note(self, text):
        """Une ligne de détail : ce qui a réellement été lu ou écrit."""
        if len(self.details) < DETAIL_LIMIT:
            self.details.append(text)
        else:
            self.detail_overflow += 1

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
    _inherit = ['itv.audit.mixin']
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

    def _itv_post_detail(self, stats):
        """Écrit dans la discussion ce que cette exécution a lu et écrit, en clair."""
        self.ensure_one()
        singular, plural = FLOW_SUBJECTS.get(self.key, ("enregistrement", "enregistrements"))
        many = stats.fetched > 1
        read = _("%(count)s %(subject)s %(verb)s dans BioTime", count=stats.fetched,
                 subject=plural if many else singular, verb=_("lus") if many else _("lu"))
        # Les compteurs à zéro n'apprennent rien : on ne garde que ce qui s'est passé.
        parts = [(stats.created, _("créés dans Odoo"), _("créé dans Odoo")),
                 (stats.updated, _("mis à jour"), _("mis à jour")),
                 (stats.unchanged, _("inchangés"), _("inchangé")),
                 (stats.errors, _("en erreur"), _("en erreur"))]
        moves = ", ".join("%s %s" % (count, plural_label if count > 1 else singular_label)
                          for count, plural_label, singular_label in parts if count)
        counts = "%s%s" % (read, (" : %s." % moves) if moves else _(" : rien à reprendre."))
        body = Markup("<p><b>%s</b></p><p>%s</p>") % (dict(SYNC_KEYS).get(self.key, self.key), counts)
        if stats.window_start and stats.window_end:
            body += Markup("<p>%s</p>") % _(
                "Fenêtre lue : du %(start)s au %(end)s (UTC)",
                start=fields.Datetime.to_string(stats.window_start),
                end=fields.Datetime.to_string(stats.window_end))
        if stats.details:
            lines = Markup().join(Markup("<li>%s</li>") % line for line in stats.details)
            body += Markup("<ul>%s</ul>") % lines
            if stats.detail_overflow:
                body += Markup("<p class='text-muted small'>%s</p>") % _(
                    "… et %(count)s autres.", count=stats.detail_overflow)
        for message in stats.messages:
            body += Markup("<p class='text-danger'>%s</p>") % message
        body += Markup("<p class='text-muted small'>%s</p>") % _(
            "%(calls)s appel(s) à BioTime, en %(duration)s s. Déclenché : %(trigger)s.",
            calls=stats.api_calls, duration=self.duration,
            trigger=dict(self._fields['trigger'].selection).get(self.trigger, self.trigger))
        self.message_post(body=body, subtype_xmlid='mail.mt_note')

    @api.autovacuum
    def _gc_sync_logs(self):
        limit = fields.Datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
        self.search([('create_date', '<', limit)]).unlink()
