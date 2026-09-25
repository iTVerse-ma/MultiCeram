# -*- coding: utf-8 -*-
"""Connexion de type CVSecurity : les passages des lecteurs deviennent des transactions Odoo.

Même fiche et même menu que BioTime : chaque lecteur est un terminal de la connexion (usage, sens,
pont UHF), chaque passage une transaction, et le calcul des journées les traite pareil.
"""
import logging
from datetime import timedelta

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.addons.itv_zk_connector.services.timeutils import (
    format_local, local_to_utc, parse_local, utc_to_local,
)

_logger = logging.getLogger(__name__)

TRANSACTIONS_PATH = 'api/v2/transaction/list'
PAGE_SIZE = 1000
MAX_PAGES = 200
READER_PREFIX = 'CV:'


class ItvZkBackend(models.Model):
    _inherit = 'itv.zk.backend'

    kind = fields.Selection(selection_add=[('cvsecurity', "CVSecurity")], ondelete={'cvsecurity': 'cascade'})
    verify_ssl = fields.Boolean(
        "Vérifier le certificat", default=True,
        help="CVSecurity : décocher pour un serveur en HTTPS avec un certificat auto-signé "
             "(installation par défaut de CVSecurity).")
    cv_watermark = fields.Datetime("Lu jusqu'au", readonly=True, copy=False,
                                   help="Fin de la dernière lecture réussie des passages CVSecurity.")
    cv_last_run = fields.Datetime("Dernière lecture", readonly=True, copy=False)
    punch_count = fields.Integer("Transactions", compute='_compute_punch_count')

    def _compute_punch_count(self):
        counts = dict(self.env['itv.zk.punch']._read_group(
            [('backend_id', 'in', self.ids)], ['backend_id'], ['__count']))
        for backend in self:
            backend.punch_count = counts.get(backend, 0)

    # -- Lecture CVSecurity ---------------------------------------------------------------------

    def _cv_fetch_page(self, start, end, page, size=PAGE_SIZE):
        self.ensure_one()
        token = self.sudo().token
        if not token:
            raise UserError(_("Renseignez le jeton d'accès CVSecurity de « %s ».", self.name))
        params = {
            'access_token': token, 'pageNo': page, 'pageSize': size,
            'startDate': format_local(utc_to_local(start, self.timezone)),
            'endDate': format_local(utc_to_local(end, self.timezone)),
        }
        url = self.url.rstrip('/') + '/' + TRANSACTIONS_PATH
        try:
            response = requests.get(url, params=params, timeout=(5, 60), verify=self.verify_ssl)
            response.raise_for_status()
            body = response.json()
        except requests.exceptions.SSLError:
            raise UserError(_("Certificat refusé par CVSecurity. Décochez « Vérifier le certificat » "
                              "pour un certificat auto-signé."))
        except requests.exceptions.HTTPError as error:
            # Jamais l'URL dans le message : elle porte le jeton, qui finirait dans la discussion.
            raise UserError(_("CVSecurity a répondu HTTP %s. Vérifiez le jeton d'accès et l'autorisation API.",
                              error.response.status_code if error.response is not None else '?'))
        except requests.RequestException as error:
            raise UserError(_("CVSecurity injoignable (%s). Vérifiez l'URL et le réseau.", type(error).__name__))
        except ValueError:
            raise UserError(_("CVSecurity n'a pas renvoyé de données lisibles : jeton refusé ou API non autorisée."))
        if str(body.get('code', '0')) not in ('0', '200'):
            raise UserError(_("CVSecurity a refusé la demande : %s", body.get('message') or body))
        data = body.get('data') or {}
        return data.get('data') or [], bool(data.get('lastPage', True))

    def _cv_fetch(self, start, end):
        rows, page = [], 1
        while page <= MAX_PAGES:
            batch, last = self._cv_fetch_page(start, end, page)
            rows += batch
            if last or not batch:
                break
            page += 1
        return rows

    # -- Transactions ---------------------------------------------------------------------------

    def _cv_terminal_for(self, reader_name):
        """Le lecteur est un terminal de la connexion : usage, sens, fuseau, pont UHF."""
        Terminal = self.env['itv.zk.terminal'].sudo().with_context(active_test=False)
        sn = READER_PREFIX + reader_name
        terminal = Terminal.search([('backend_id', '=', self.id), ('sn', '=', sn)], limit=1)
        if terminal:
            return terminal
        return Terminal.create({
            'backend_id': self.id, 'sn': sn,
            'alias': reader_name, 'usage': 't', 'direction': Terminal._itv_guess_direction(reader_name),
            'is_uhf_bridge': True, 'is_virtual': True,
        })

    def _cv_employee_for(self, pin):
        if not pin:
            return self.env['hr.employee']
        return self.env['hr.employee'].sudo().with_context(active_test=False).search(
            ['|', ('itv_cv_pin', '=', pin), ('itv_cv_pin2', '=', pin)], limit=1)

    def _cv_import_transactions(self, rows):
        """Crée les transactions encore inconnues ; rend les nouvelles."""
        self.ensure_one()
        Punch = self.env['itv.zk.punch'].sudo()
        backend = self
        created = Punch.browse()
        for row in rows:
            pin = str(row.get('pin') or '').strip()
            local = str(row.get('eventTime') or '').strip()
            reader_name = str(row.get('readerName') or row.get('eventPointName') or row.get('devName') or '').strip()
            if not local or not reader_name:
                continue
            key = str(row.get('id') or '|'.join((pin, local, reader_name)))
            if Punch.search_count([('backend_id', '=', backend.id), ('cv_key', '=', key)]):
                continue
            terminal = self._cv_terminal_for(reader_name)
            employee = self._cv_employee_for(pin)
            created |= Punch.create({
                'backend_id': backend.id, 'source': 'cvsecurity', 'cv_key': key, 'cv_pin': pin or False,
                'emp_code': employee.barcode or False, 'employee_id': employee.id or False,
                'punch_local': local,
                'punch_time': local_to_utc(local, terminal.timezone_override or self.timezone),
                'punch_date': parse_local(local).date(),
                'terminal_id': terminal.id, 'terminal_sn': terminal.sn, 'terminal_alias': terminal.alias,
                'verify_type': str(row.get('verifyModeName') or '') or False,
                'upload_time': fields.Datetime.now(),
            })
        if created:
            created._on_punches_imported()
        return created

    # -- Exécution ------------------------------------------------------------------------------

    def _cv_sync(self):
        self.ensure_one()
        now = fields.Datetime.now()
        start = ((self.cv_watermark or now - timedelta(days=self.initial_sync_days or 1))
                 - timedelta(minutes=self.overlap_minutes))
        try:
            rows = self._cv_fetch(start, now)
            created = self._cv_import_transactions(rows)
        except UserError as error:
            self.sudo()._record_failure(str(error))
            self.sudo().cv_last_run = now
            self._itv_audit(_("Lecture CVSecurity en échec"), [str(error)])
            return False
        self.sudo()._record_success()
        self.sudo().write({'cv_last_run': now, 'cv_watermark': now})
        if created:
            orphans = created.filtered(lambda punch: not punch.employee_id)
            details = [_("%(read)s passage(s) lu(s) dans CVSecurity, %(new)s nouvelle(s) transaction(s)",
                         read=len(rows), new=len(created))]
            if orphans:
                details.append(_("%(count)s sans employé : PIN %(pins)s à saisir sur les fiches",
                                 count=len(orphans), pins=", ".join(sorted(set(orphans.mapped('cv_pin')))[:10])))
            details += ["%s — %s sur %s" % (punch.punch_local, punch.employee_id.name or punch.cv_pin,
                                           punch.terminal_id.alias) for punch in created[:40]]
            self._itv_audit(_("Passages CVSecurity importés"), details)
        return True

    def action_test_connection(self):
        if self.kind != 'cvsecurity':
            return super().action_test_connection()
        self.ensure_one()
        now = fields.Datetime.now()
        rows, _last = self._cv_fetch_page(now - timedelta(days=1), now, 1, size=5)
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'success', 'title': _("CVSecurity répond"),
                       'message': _("%s passage(s) lu(s) sur les dernières 24 h (échantillon).", len(rows))},
        }

    def action_sync_now(self):
        cv = self.filtered(lambda backend: backend.kind == 'cvsecurity')
        for backend in cv:
            backend._cv_sync()
        if self - cv:
            return super(ItvZkBackend, self - cv).action_sync_now()
        return True

    def action_view_transactions(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('itv_zk_connector.itv_zk_punch_action')
        action['domain'] = [('backend_id', '=', self.id)]
        action['context'] = {}
        return action

    @api.model
    def _cron_cv_sync(self):
        for backend in self.search([('kind', '=', 'cvsecurity')]):
            backend._cv_sync()
            self.env.cr.commit()
