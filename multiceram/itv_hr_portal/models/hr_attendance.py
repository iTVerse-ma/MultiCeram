# -*- coding: utf-8 -*-
from odoo import fields, models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    itv_anomaly_flow = fields.Selection(related='itv_day_id.itv_anomaly_flow', string="Traitement", store=True)
    itv_portal_state = fields.Selection(related='itv_day_id.itv_portal_state', string="Justification portail", store=True)
    itv_portal_reason = fields.Text(related='itv_day_id.itv_portal_reason', string="Explication de l'employé")
    itv_portal_message = fields.Char(related='itv_day_id.itv_portal_message', string="Message à l'employé")
    itv_portal_date = fields.Datetime(related='itv_day_id.itv_portal_date', string="Expliquée le")
    itv_portal_sent_date = fields.Datetime(related='itv_day_id.itv_portal_sent_date', string="Envoyée à l'employé le")

    def action_itv_portal_send(self):
        return self.itv_day_id.action_itv_portal_send()

    def action_itv_anomaly_overtime(self):
        return self.itv_day_id.action_itv_anomaly_overtime()

    def action_itv_portal_accept(self):
        return self.itv_day_id.action_itv_portal_accept()

    def action_itv_portal_refuse_back(self):
        return self.itv_day_id.action_itv_portal_refuse_back()

    def action_itv_portal_refuse_close(self):
        return self.itv_day_id.action_itv_portal_refuse_close()
