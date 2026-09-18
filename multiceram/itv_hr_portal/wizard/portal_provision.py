# -*- coding: utf-8 -*-
"""Création en masse des comptes portail des employés.

Règles :
- un employé déjà relié à un utilisateur n'est jamais touché (il travaille dans le back-office) ;
- l'identifiant est le matricule (`barcode`), unique dans la base ;
- aucun mot de passe n'est posé : chaque compte reçoit un lien d'activation à usage unique,
  que l'employé utilise pour choisir son propre mot de passe (aucune adresse e-mail requise).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

class ItvHrPortalProvision(models.TransientModel):
    _name = 'itv.hr.portal.provision'
    _description = "Création des comptes portail"

    employee_ids = fields.Many2many('hr.employee', string="Employés", required=True)
    eligible_count = fields.Integer("À créer", compute='_compute_counts')
    skipped_user_count = fields.Integer("Déjà un compte", compute='_compute_counts')
    skipped_badge_count = fields.Integer("Sans matricule", compute='_compute_counts')
    user_ids = fields.Many2many('res.users', string="Comptes créés", readonly=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'hr.employee' and self.env.context.get('active_ids'):
            values['employee_ids'] = [(6, 0, self.env.context['active_ids'])]
        return values

    @api.depends('employee_ids')
    def _compute_counts(self):
        for wizard in self:
            employees = wizard.employee_ids
            with_user = employees.filtered('user_id')
            without_badge = (employees - with_user).filtered(lambda employee: not employee.barcode)
            wizard.skipped_user_count = len(with_user)
            wizard.skipped_badge_count = len(without_badge)
            wizard.eligible_count = len(employees) - len(with_user) - len(without_badge)

    def _eligible_employees(self):
        self.ensure_one()
        return self.employee_ids.filtered(lambda employee: not employee.user_id and employee.barcode)

    def action_create_accounts(self):
        """Crée les comptes manquants et prépare leur lien d'activation."""
        self.ensure_one()
        if not self.env.user.has_group('hr.group_hr_manager'):
            raise UserError(_("Seul un responsable RH peut créer les comptes portail."))
        employees = self._eligible_employees()
        if not employees:
            raise UserError(_("Aucun employé éligible : ils ont déjà un compte ou pas de matricule."))
        Users = self.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True)
        portal_group = self.env.ref('base.group_portal')
        created = Users.browse()
        for employee in employees:
            login = employee.barcode.strip()
            if Users.with_context(active_test=False).search_count([('login', '=', login)]):
                continue  # identifiant déjà pris : laissé aux RH
            user = Users.create({
                'name': employee.name,
                'login': login,
                'group_ids': [(6, 0, [portal_group.id])],
                'company_id': employee.company_id.id or self.env.company.id,
                'company_ids': [(6, 0, [employee.company_id.id or self.env.company.id])],
            })
            employee.user_id = user.id
            created |= user
        # Le lien d'activation est engendré à la demande (Odoo 19) : on marque seulement le type.
        created.mapped('partner_id').sudo().signup_prepare(signup_type='signup')
        self.user_ids = [(6, 0, created.ids)]
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context, itv_created=len(created)),
        }

    def action_print_letters(self):
        """Courriers d'activation : un employé par page, avec QR vers le lien."""
        self.ensure_one()
        if not self.user_ids:
            raise UserError(_("Aucun compte à imprimer."))
        return self.env.ref('itv_hr_portal.action_report_portal_activation').report_action(self.user_ids)
