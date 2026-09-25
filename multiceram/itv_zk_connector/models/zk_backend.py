# -*- coding: utf-8 -*-
import logging
import time
from contextlib import contextmanager
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from odoo import _, api, fields, models, sql_db
from odoo.exceptions import UserError, ValidationError

from ..services.biotime_client import BioTimeClient, BioTimeError
from .zk_sync_log import SyncStats

_logger = logging.getLogger(__name__)

# Espace de noms des verrous consultatifs PostgreSQL de ce module (entier arbitraire).
SYNC_LOCK_NAMESPACE = 734121
CIRCUIT_FAILURES = 3
CIRCUIT_PAUSE = timedelta(minutes=10)


class ItvZkBackend(models.Model):
    _name = 'itv.zk.backend'
    _description = "Connexion de pointage"
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char("Nom", required=True, tracking=True,
                       help="Nom libre, affiché partout où un terminal ou un pointage renvoie à ce serveur "
                            "(ex. « BioTime MultiCeram » pour le serveur de production).")
    kind = fields.Selection(
        [('biotime', "BioTime")], string="Type", required=True, default='biotime', tracking=True,
        help="Logiciel interrogé par cette connexion. Ses terminaux et ses transactions portent son nom.")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Société", required=True, default=lambda self: self.env.company)
    url = fields.Char(
        "URL du serveur", required=True, tracking=True,
        help="Adresse racine du serveur BioTime, protocole et port compris : http://192.168.1.120:8090/\n"
             "C'est la même adresse que celle utilisée pour ouvrir BioTime dans un navigateur. "
             "Odoo y ajoute lui-même les chemins de l'API (/api-token-auth/, /iclock/api/…).\n"
             "Elle doit être joignable depuis le serveur Odoo : une adresse en 127.0.0.1 ne fonctionne "
             "que si BioTime tourne sur la même machine.")
    auth_mode = fields.Selection(
        [('token', "Jeton (Token)"), ('jwt', "JWT"), ('basic', "Authentification basique")],
        string="Authentification", required=True, default='token',
        help="Jeton (Token) : mode normal de BioTime 8 et 9. Odoo envoie l'utilisateur et le mot de passe "
             "à /api-token-auth/ et réutilise le jeton renvoyé jusqu'à son expiration.\n"
             "JWT et Authentification basique ne servent que pour des installations particulières.")
    username = fields.Char(
        "Utilisateur API", groups='base.group_system',
        help="Identifiant d'un compte BioTime, le même que pour l'interface web de BioTime.\n"
             "À créer dans BioTime : Système → Gestion des utilisateurs → Utilisateur, avec un rôle "
             "autorisant au minimum le personnel, les terminaux et les pointages.\n"
             "Utilisez un compte dédié à Odoo plutôt que le compte administrateur : il est ainsi "
             "révocable sans bloquer personne. Le module « API » doit être présent dans la licence BioTime.")
    password = fields.Char(
        "Mot de passe API", groups='base.group_system',
        help="Mot de passe de ce compte BioTime. Odoo ne le transmet qu'à ce serveur, pour obtenir un jeton.\n"
             "Changer le mot de passe dans BioTime invalide le jeton : il faut le remettre à jour ici.")
    token = fields.Char("Jeton", groups='base.group_system', copy=False)
    timezone = fields.Char("Fuseau horaire", required=True, default='Africa/Casablanca',
                           help="Fuseau des heures envoyées par le serveur BioTime.")
    page_size = fields.Integer(
        "Taille de page", default=1000,
        help="Nombre d'enregistrements demandés par appel. BioTime plafonne souvent à 1000 : "
             "au-delà il renvoie silencieusement moins de lignes.")
    page_size_param = fields.Char("Paramètre de taille de page", required=True, default='page_size',
                                  help="page_size (BioTime 9) ou limit (BioTime 8).")
    read_only = fields.Boolean("Lecture seule", default=True, tracking=True,
                               help="Aucune écriture vers BioTime (pointages manuels, plannings, passages UHF).")
    initial_sync_days = fields.Integer(
        "Historique initial (jours)", default=1,
        help="Profondeur reprise lors de la toute première synchronisation, quand aucun filigrane n'existe encore. "
             "Ensuite, seul le recouvrement s'applique.")
    overlap_minutes = fields.Integer("Recouvrement (min)", default=30,
                                     help="Chaque import repart de la fin du précédent moins ce recouvrement, pour "
                                          "reprendre les pointages arrivés avec un peu de retard. Réglé par le mode de "
                                          "synchronisation (Présences → Configuration) ; les gros retards (terminal hors ligne) sont "
                                          "rattrapés au retour en ligne du terminal et par la réconciliation nocturne.")
    reconcile_days = fields.Integer("Réconciliation (jours)", default=35,
                                    help="Profondeur de la comparaison quotidienne des comptages BioTime / Odoo.")
    offline_after_minutes = fields.Integer(
        "Hors ligne après (min)", default=30,
        help="Délai sans activité au-delà duquel un terminal est signalé hors ligne.")
    status = fields.Selection(
        [('ok', "Opérationnel"), ('degraded', "Dégradé"), ('down', "Indisponible")],
        string="Santé", required=True, default='ok', readonly=True, tracking=True)
    down_since = fields.Datetime("Indisponible depuis", readonly=True)
    failure_count = fields.Integer("Échecs consécutifs", readonly=True)
    last_error = fields.Text("Dernière erreur", readonly=True)
    terminal_ids = fields.One2many('itv.zk.terminal', 'backend_id', string="Terminaux")
    terminal_count = fields.Integer("Nombre de terminaux", compute='_compute_terminal_count')
    state_ids = fields.One2many('itv.zk.sync.state', 'backend_id', string="États de synchronisation")

    @api.depends('terminal_ids')
    def _compute_terminal_count(self):
        for backend in self:
            backend.terminal_count = len(backend.terminal_ids)

    @api.constrains('timezone')
    def _check_timezone(self):
        for backend in self:
            try:
                ZoneInfo(backend.timezone)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValidationError(_("Fuseau horaire inconnu : %s", backend.timezone))

    @api.constrains('page_size', 'overlap_minutes', 'reconcile_days')
    def _check_positive_settings(self):
        for backend in self:
            if backend.page_size <= 0 or backend.overlap_minutes < 0 or backend.reconcile_days < 0:
                raise ValidationError(_("La taille de page doit être positive, le recouvrement et la réconciliation ne peuvent pas être négatifs."))

    # -- Client -----------------------------------------------------------------

    def _get_client(self):
        self.ensure_one()
        backend = self.sudo()

        def store_token(token):
            backend.token = token

        return BioTimeClient(
            backend.url,
            auth_mode=backend.auth_mode,
            username=backend.username,
            password=backend.password,
            token=backend.token,
            read_only=backend.read_only,
            on_token=store_token,
        )

    # -- Exécution : verrou, coupe-circuit, journal ----------------------------------

    @contextmanager
    def _sync_lock(self, state):
        """Verrou consultatif PostgreSQL tenu par une connexion dédiée pendant toute l'exécution.

        Plusieurs workers peuvent lancer le même flux en parallèle. La connexion dédiée
        garde le verrou pendant que le curseur principal valide page par page.
        """
        cr = sql_db.db_connect(self.env.cr.dbname).cursor()
        try:
            cr.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (SYNC_LOCK_NAMESPACE, state.id))
            yield cr.fetchone()[0]
        finally:
            cr.rollback()
            cr.close()

    def _is_circuit_open(self):
        self.ensure_one()
        return bool(self.status == 'down' and self.down_since
                    and self.down_since > fields.Datetime.now() - CIRCUIT_PAUSE)

    def _record_success(self):
        if self.status != 'ok' or self.failure_count:
            self.write({'status': 'ok', 'failure_count': 0, 'down_since': False, 'last_error': False})

    def _record_failure(self, message):
        _logger.warning("Connexion %s : %s", self.name, message)
        failures = self.failure_count + 1
        vals = {'failure_count': failures, 'last_error': message, 'status': 'degraded'}
        if failures >= CIRCUIT_FAILURES:
            vals.update(status='down', down_since=fields.Datetime.now())
        self.write(vals)

    def _checkpoint(self, processed):
        """Valide la progression dans un cron ; sans effet ailleurs (tests, boutons)."""
        if self.env.context.get('cron_id'):
            self.env['ir.cron']._commit_progress(processed)

    def _run_sync(self, key, trigger='cron'):
        """Exécute le flux `key` (méthode `_sync_<key>`) et consigne le résultat dans le journal."""
        self.ensure_one()
        method = getattr(self, '_sync_%s' % key)
        Log = self.env['itv.zk.sync.log'].with_context(mail_create_nolog=True)
        log_vals = {'backend_id': self.id, 'key': key, 'trigger': trigger}
        # Le flux des terminaux sert de sonde : il tourne même quand le circuit est ouvert.
        if key != 'terminals' and self._is_circuit_open():
            return Log.create(dict(log_vals, status='skipped_down',
                                   message=_("BioTime indisponible : nouvel essai après la pause du coupe-circuit.")))
        state = self.env['itv.zk.sync.state']._get(self, key)
        started = time.monotonic()
        stats = SyncStats()
        with self._sync_lock(state) as acquired:
            if not acquired:
                return Log.create(dict(log_vals, status='skipped_locked'))
            try:
                method(state, stats)
            except BioTimeError as exc:
                status = 'failed'
                stats.messages.append(str(exc))
                self._record_failure(str(exc))
            else:
                status = 'partial' if (stats.incomplete or stats.errors) else 'success'
                self._record_success()
        log = Log.create(dict(log_vals, status=status, duration=round(time.monotonic() - started, 2),
                              **stats.log_vals()))
        log._itv_post_detail(stats)
        if stats.incomplete and self.env.context.get('cron_id'):
            # Fenêtre non terminée dans le temps imparti : le planificateur relance aussitôt.
            self.env['ir.cron']._commit_progress(remaining=1)
        return log

    @api.model
    def _cron_sync(self, key):
        for backend in self.search([('kind', '=', 'biotime')]):
            backend._run_sync(key)

    # -- Actions ---------------------------------------------------------------------------

    def action_test_connection(self):
        self.ensure_one()
        try:
            data = self._get_client().get('iclock/api/terminals/', {self.page_size_param: 1})
        except BioTimeError as exc:
            raise UserError(_("Connexion à BioTime impossible : %s", exc)) from exc
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Connexion BioTime"),
                'message': _("Connexion réussie : %s terminal(s) déclaré(s) dans BioTime.", data.get('count', 0)),
            },
        }

    def action_sync_now(self):
        # Tout ce qui vient de la pointeuse : terminaux, employés créés dessus, puis pointages.
        for xmlid in ('itv_zk_connector.ir_cron_itv_zk_terminals', 'itv_zk_connector.ir_cron_itv_zk_employees',
                      'itv_zk_connector.ir_cron_itv_zk_transactions'):
            self.env.ref(xmlid).sudo()._trigger()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'info',
                'title': _("Synchronisation lancée"),
                'message': _("Terminaux, employés et pointages : résultats dans le journal de synchronisation d'ici une minute."),
            },
        }
