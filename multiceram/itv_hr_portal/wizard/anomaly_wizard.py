# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class ItvAttendanceAnomalyWizard(models.TransientModel):
    _inherit = 'itv.attendance.anomaly.wizard'

    resolution = fields.Selection(
        selection_add=[('sent', "Envoyer à l'employé"), ('overtime', "Passer en heures supplémentaires")],
        ondelete={'sent': 'cascade', 'overtime': 'cascade'}, default='sent')
    overtime_hours = fields.Float("Heures à déclarer", digits=(2, 2),
                                  help="Durée mise en circuit de validation N1 / N2.")
    overtime_rate = fields.Selection([('25', "25 %"), ('50', "50 %"), ('100', "100 %")],
                                     string="Taux", default='25')
    message = fields.Char("Message à l'employé",
                          help="Ce que vous demandez d'expliquer : l'employé le lit dans son portail.")

    def action_apply(self):
        """« Envoyer à l'employé » : l'anomalie apparaît dans son portail, il écrit son explication."""
        self.ensure_one()
        if self.resolution == 'overtime':
            days = self.day_ids.filtered('anomaly_state')
            if not days:
                raise UserError(_("Aucune journée sélectionnée n'a d'anomalie."))
            days.check_access('read')
            days.sudo()._itv_refer_overtime(self.overtime_hours, self.overtime_rate, self.note or False)
            return {'type': 'ir.actions.act_window_close'}
        if self.resolution != 'sent':
            return super().action_apply()
        days = self.day_ids.filtered('anomaly_state')
        if not days:
            raise UserError(_("Aucune journée sélectionnée n'a d'anomalie."))
        days.check_access('read')
        days.sudo()._itv_portal_send(self.message or False)
        return {'type': 'ir.actions.act_window_close'}
