# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    itv_cv_pin = fields.Char(
        "PIN CVSecurity", groups='hr.group_hr_user', tracking=True, copy=False,
        help="Identifiant de la personne dans CVSecurity (badge UHF). Sert à retrouver l'employé "
             "derrière chaque passage à la barrière.")
    itv_cv_pin2 = fields.Char(
        "PIN CVSecurity 2", groups='hr.group_hr_user', tracking=True, copy=False,
        help="Second identifiant CVSecurity, pour un employé enregistré deux fois (second badge, véhicule).")

    def write(self, vals):
        result = super().write(vals)
        pins = [vals[name] for name in ('itv_cv_pin', 'itv_cv_pin2') if vals.get(name)]
        if pins and len(self) == 1:
            # Passages arrivés avant que le PIN soit saisi : ils rejoignent l'employé et ses journées.
            orphans = self.env['itv.zk.punch'].sudo().search([
                ('source', '=', 'cvsecurity'), ('employee_id', '=', False), ('cv_pin', 'in', pins)])
            if orphans:
                orphans.write({'employee_id': self.id, 'emp_code': self.barcode or False})
                orphans._on_punches_imported()
        return result
