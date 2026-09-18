# -*- coding: utf-8 -*-
"""Algorithmes de synchronisation BioTime → Odoo : pointages, terminaux, employés."""
import hashlib
import json
import logging
import time
from datetime import timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.timeutils import format_local, local_to_utc, utc_to_local

TRANSACTIONS_PATH = 'iclock/api/transactions/'
TERMINALS_PATH = 'iclock/api/terminals/'
EMPLOYEES_PATH = 'personnel/api/employees/'
DEPARTMENTS_PATH = 'personnel/api/departments/'
# Durée maximale d'une exécution avant de rendre la main au planificateur.
TIME_BOX_SECONDS = 120

_logger = logging.getLogger(__name__)


class ItvZkBackend(models.Model):
    _inherit = 'itv.zk.backend'

    # -- Pointages ------------------------------------------------------------------

    def _sync_transactions(self, state, stats):
        """Import incrémental : une requête globale sur [filigrane − recouvrement, maintenant].

        BioTime n'offre pas de curseur incrémental documenté : la fenêtre recouvre la
        précédente, et l'unicité sur l'identifiant BioTime rend toute reprise sans effet.
        """
        now = fields.Datetime.now()
        start = (state.watermark or now - timedelta(days=self.initial_sync_days)) - timedelta(minutes=self.overlap_minutes)
        if self._import_transaction_window(stats, start, now):
            state.write({'watermark': now, 'last_success': now})
        self._check_employee_count()

    def _check_employee_count(self):
        """Employé créé ou supprimé sur la pointeuse : il arrive dans Odoo au rythme des pointages.

        BioTime ne filtre pas les employés par date de modification : on ne lui demande que leur
        nombre (une ligne), et la synchronisation complète ne part que s'il a changé.
        Les simples modifications suivent la cadence normale de la synchronisation des employés.
        """
        state = self.env['itv.zk.sync.state']._get(self, 'employees')
        try:
            response = self._get_client().request('GET', EMPLOYEES_PATH, params={self.page_size_param: 1})
        except Exception as error:  # le contrôle ne doit jamais faire échouer l'import des pointages
            _logger.warning("BioTime %s : comptage des employés impossible (%s)", self.name, error)
            return
        count = (response or {}).get('count')
        if count is not None and count != (state.cursor or {}).get('count'):
            self.env.ref('itv_zk_connector.ir_cron_itv_zk_employees').sudo()._trigger()

    def _import_transaction_window(self, stats, start, end, extra_params=None):
        """Importe les pointages d'une fenêtre UTC. Rend False si le temps imparti est écoulé."""
        client = self._get_client()
        params = {
            'start_time': format_local(utc_to_local(start, self.timezone)),
            'end_time': format_local(utc_to_local(end, self.timezone)),
            self.page_size_param: self.page_size,
        }
        params.update(extra_params or {})
        stats.extend_window(start, end)
        Punch = self.env['itv.zk.punch']
        deadline = time.monotonic() + TIME_BOX_SECONDS
        try:
            for page in client.iter_pages(TRANSACTIONS_PATH, params):
                records = page['data']
                with self.env.cr.savepoint():
                    created = Punch._import_biotime_transactions(self, records)
                stats.fetched += len(records)
                stats.created += len(created)
                stats.unchanged += len(records) - len(created)
                self._checkpoint(len(records))
                if time.monotonic() > deadline:
                    stats.incomplete = True
                    return False
        finally:
            stats.api_calls += client.calls
        return True

    def _sync_reconcile(self, state, stats):
        """Compare jour par jour les comptages BioTime et Odoo ; réimporte les jours incomplets.

        Un terminal hors ligne téléverse ses pointages en retard (jusqu'à trois semaines dans
        l'historique MultiCeram), bien au-delà du recouvrement de l'import incrémental.
        """
        client = self._get_client()
        Punch = self.env['itv.zk.punch']
        today = utc_to_local(fields.Datetime.now(), self.timezone).date()
        incomplete_days = []
        try:
            for offset in range(1, self.reconcile_days + 1):
                day = today - timedelta(days=offset)
                remote = client.count(
                    TRANSACTIONS_PATH,
                    {'start_time': '%s 00:00:00' % day, 'end_time': '%s 23:59:59' % day},
                    page_size_param=self.page_size_param,
                )
                local = Punch.search_count([
                    ('backend_id', '=', self.id), ('source', '=', 'device'), ('punch_date', '=', day),
                ])
                if remote > local:
                    incomplete_days.append(day)
        finally:
            stats.api_calls += client.calls
        for day in sorted(incomplete_days):
            start = local_to_utc('%s 00:00:00' % day, self.timezone)
            end = local_to_utc('%s 23:59:59' % day, self.timezone)
            if not self._import_transaction_window(stats, start, end):
                break
        if incomplete_days:
            stats.messages.append(_("Jours réimportés : %s", ", ".join(str(day) for day in sorted(incomplete_days))))
        else:
            stats.messages.append(_("Aucun écart de comptage."))
        state.last_success = fields.Datetime.now()

    # -- Terminaux ------------------------------------------------------------------

    def _sync_terminals(self, state, stats):
        """Met à jour les terminaux et leur santé ; rattrape les pointages d'un terminal revenu en ligne."""
        client = self._get_client()
        Terminal = self.env['itv.zk.terminal'].with_context(active_test=False)
        now = fields.Datetime.now()
        offline_limit = now - timedelta(minutes=self.offline_after_minutes)
        terminals = {terminal.sn: terminal for terminal in Terminal.search([('backend_id', '=', self.id)])}
        back_online = Terminal
        try:
            for record in client.iter_records(TERMINALS_PATH, {self.page_size_param: self.page_size}):
                stats.fetched += 1
                serial = (record.get('sn') or '').strip()
                if not serial:
                    stats.errors += 1
                    continue
                last_activity = local_to_utc(record['last_activity'], self.timezone) if record.get('last_activity') else False
                online = bool(last_activity and last_activity >= offline_limit)
                area = record.get('area') if isinstance(record.get('area'), dict) else {}
                vals = {
                    'biotime_id': record.get('id') or 0,
                    'alias': record.get('alias') or serial,
                    'ip_address': record.get('ip_address') or False,
                    'area_name': area.get('area_name') or False,
                    'biotime_area_id': area.get('id') or 0,
                    'biotime_state': str(record['state']) if record.get('state') is not None else False,
                    'terminal_tz': str(record['terminal_tz']) if record.get('terminal_tz') is not None else False,
                    'last_activity': last_activity,
                }
                terminal = terminals.get(serial)
                if terminal:
                    if online and terminal.offline_since:
                        back_online |= terminal
                    elif not online and not terminal.offline_since:
                        vals['offline_since'] = last_activity or now
                    terminal.write(vals)
                    stats.updated += 1
                else:
                    vals.update(backend_id=self.id, sn=serial, offline_since=False if online else (last_activity or now))
                    terminals[serial] = Terminal.create(vals)
                    stats.created += 1
        finally:
            stats.api_calls += client.calls
        for terminal in back_online:
            # Revenu en ligne : le terminal a pu téléverser des pointages anciens.
            since = terminal.offline_since - timedelta(hours=1)
            if not self._import_transaction_window(stats, since, now, {'terminal_sn': terminal.sn}):
                break
            terminal.offline_since = False
        state.last_success = now

    # -- Employés et départements ------------------------------------------------------

    def _sync_employees(self, state, stats):
        """Employés rapprochés par matricule (badge = emp_code BioTime). Ne crée jamais d'utilisateur."""
        client = self._get_client()
        try:
            department_ids = self._sync_departments(client)
            Employee = self.env['hr.employee'].sudo().with_context(active_test=False, tracking_disable=True)
            employees = {employee.barcode: employee for employee in Employee.search([('barcode', '!=', False)])}
            for record in client.iter_records(EMPLOYEES_PATH, {self.page_size_param: self.page_size}):
                stats.fetched += 1
                code = (record.get('emp_code') or '').strip()
                if not code:
                    stats.errors += 1
                    continue
                vals = self._prepare_employee_vals(record, department_ids)
                digest = hashlib.sha1(json.dumps(vals, sort_keys=True, default=str).encode()).hexdigest()
                employee = employees.get(code)
                if employee and employee.itv_biotime_sync_hash == digest:
                    stats.unchanged += 1
                    continue
                vals['itv_biotime_sync_hash'] = digest
                if employee and employee.department_id:
                    # Le département se gère dans Odoo : BioTime ne le remplit que pour une fiche qui n'en a pas
                    # (employé créé sur la pointeuse), sinon un repli côté BioTime écraserait le vrai.
                    vals.pop('department_id', None)
                try:
                    with self.env.cr.savepoint():
                        if employee:
                            employee.write(vals)
                            stats.updated += 1
                        else:
                            # Les accès portail sont créés par itv_hr_portal, jamais ici.
                            employees[code] = Employee.create(dict(
                                vals, barcode=code, company_id=self.company_id.id, itv_to_complete=True))
                            stats.created += 1
                except (ValidationError, UserError) as exc:
                    stats.errors += 1
                    stats.messages.append(_("Employé %(code)s ignoré : %(error)s", code=code, error=exc))
        finally:
            stats.api_calls += client.calls
        # Nombre vu par cette synchronisation : référence du contrôle fait à chaque import de pointages.
        state.write({'last_success': fields.Datetime.now(), 'cursor': dict(state.cursor or {}, count=stats.fetched)})

    def _prepare_employee_vals(self, record, department_ids):
        """Champs repris de BioTime. Le hash du mot de passe (self_password) n'est jamais lu."""
        name = " ".join(part for part in (
            (record.get('first_name') or '').strip(),
            (record.get('last_name') or '').strip(),
        ) if part)
        vals = {'name': name or record['emp_code'], 'itv_biotime_emp_id': record.get('id') or 0}
        department = record.get('department')
        if isinstance(department, dict) and department_ids.get(department.get('id')):
            vals['department_id'] = department_ids[department['id']]
        return vals

    def _sync_departments(self, client):
        """Départements rapprochés par identifiant BioTime ; rend {id BioTime: id Odoo}."""
        Department = self.env['hr.department'].sudo().with_context(active_test=False)
        departments = {department.itv_biotime_dept_id: department
                       for department in Department.search([('itv_biotime_dept_id', '!=', 0)])}
        parents = {}
        for record in client.iter_records(DEPARTMENTS_PATH, {self.page_size_param: self.page_size}):
            biotime_id = record.get('id')
            if not biotime_id:
                continue
            vals = {
                'name': record.get('dept_name') or record.get('dept_code') or str(biotime_id),
                'itv_biotime_dept_code': record.get('dept_code') or False,
            }
            department = departments.get(biotime_id)
            if not department:
                departments[biotime_id] = Department.create(dict(vals, itv_biotime_dept_id=biotime_id, company_id=self.company_id.id))
            elif (department.name, department.itv_biotime_dept_code or False) != (vals['name'], vals['itv_biotime_dept_code']):
                department.write(vals)
            parent = record.get('parent_dept')
            if isinstance(parent, dict):
                parent = parent.get('id')
            if parent:
                parents[biotime_id] = parent
        for biotime_id, parent_id in parents.items():
            parent = departments.get(parent_id)
            if parent and departments[biotime_id].parent_id != parent:
                departments[biotime_id].parent_id = parent
        return {biotime_id: department.id for biotime_id, department in departments.items()}
