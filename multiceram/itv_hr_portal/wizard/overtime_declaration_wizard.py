# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

DEFAULT_QUESTION = "Combien d'heures supplémentaires avez-vous faites ce jour-là ?"


class ItvOvertimeDeclarationWizard(models.TransientModel):
    _name = 'itv.overtime.declaration.wizard'
    _description = "Demander à l'employé ses heures supplémentaires"

    question = fields.Char("Question à l'employé", required=True, default=DEFAULT_QUESTION,
                           help="L'employé voit cette question dans son portail, sans le nombre d'heures calculé.")

    def action_send(self):
        self.ensure_one()
        lines = self.env['hr.attendance.overtime.line'].browse(self.env.context.get('active_ids', []))
        if not lines:
            raise UserError(_("Aucune heure supplémentaire sélectionnée."))
        lines._itv_ask_declaration(self.question)
        return {'type': 'ir.actions.act_window_close'}
