# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    itv_biotime_pin = fields.Char(
        "PIN pointeuse", groups='hr.group_hr_user', copy=False,
        help="Code numérique saisi sur la pointeuse (device_password côté BioTime). "
             "Le matricule sert d'identifiant ; ce PIN n'est utilisé que pour la saisie clavier.")
    itv_push_state = fields.Selection([
        ('draft', "Non envoyé"),
        ('queued', "En file"),
        ('sent', "Envoyé"),
        ('error', "Erreur"),
    ], string="Envoi BioTime", default='draft', groups='hr.group_hr_user', copy=False, readonly=True)
    itv_push_error = fields.Text("Dernière erreur d'envoi", groups='hr.group_hr_user', copy=False, readonly=True)
    itv_pushed_at = fields.Datetime("Envoyé à BioTime le", groups='hr.group_hr_user', copy=False, readonly=True)

    # Champs qui, modifiés, doivent repartir vers BioTime.
    ITV_PUSH_FIELDS = ('name', 'barcode', 'itv_biotime_pin', 'department_id', 'active')

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        employees._itv_auto_push()
        return employees

    def write(self, vals):
        result = super().write(vals)
        if any(name in vals for name in self.ITV_PUSH_FIELDS) and not self.env.context.get('itv_skip_push'):
            # La synchronisation descendante écrit ce hash : ne pas renvoyer ce qu'on vient de recevoir.
            if 'itv_biotime_sync_hash' not in vals:
                self._itv_auto_push()
        return result

    def _itv_auto_push(self):
        """Envoi automatique vers BioTime, silencieux : un échec laisse la demande dans la file."""
        if self.env.context.get('itv_skip_push') or self.env.context.get('install_mode'):
            return
        backend = self.env['itv.zk.backend'].search([('active', '=', True), ('read_only', '=', False)])
        if len(backend) != 1:
            return          # aucune connexion ouverte en écriture, ou plusieurs : on ne devine pas
        Outbox = self.env['itv.zk.outbox']
        entries = Outbox.browse()
        for employee in self.filtered('barcode'):
            entries |= Outbox._enqueue_employee(employee, backend)
        if entries:
            entries.with_context(itv_skip_push=True)._process_employee()

    def _itv_push_backend(self):
        """Connexion à utiliser pour écrire : seules les connexions non « lecture seule » sont éligibles.

        Plusieurs connexions peuvent coexister (serveur du client, serveur de test) : on n'écrit jamais
        dans celles laissées en lecture seule, et on refuse de choisir s'il y en a plusieurs ouvertes.
        """
        Backend = self.env['itv.zk.backend']
        if not Backend.search_count([('active', '=', True)]):
            raise UserError(_("Aucune connexion BioTime n'est configurée."))
        writable = Backend.search([('active', '=', True), ('read_only', '=', False)])
        if not writable:
            raise UserError(_("Toutes les connexions BioTime sont en lecture seule : "
                              "décochez l'option sur celle qui doit recevoir les employés."))
        if len(writable) > 1:
            raise UserError(_("Plusieurs connexions BioTime sont ouvertes en écriture (%s) : "
                              "n'en laissez qu'une pour éviter d'envoyer les employés au mauvais serveur.")
                            % ", ".join(writable.mapped('name')))
        return writable

    def action_push_to_biotime(self):
        """Envoie immédiatement les employés sélectionnés vers BioTime."""
        backend = self._itv_push_backend()
        Outbox = self.env['itv.zk.outbox']
        entries = Outbox.browse()
        for employee in self:
            entries |= Outbox._enqueue_employee(employee, backend)
        self.write({'itv_push_state': 'queued'})
        entries._process_employee()
        failed = self.filtered(lambda employee: employee.itv_push_state == 'error')
        if failed:
            raise UserError(_("Envoi refusé pour %s : %s") % (failed[0].display_name, failed[0].itv_push_error or ''))
        return True
