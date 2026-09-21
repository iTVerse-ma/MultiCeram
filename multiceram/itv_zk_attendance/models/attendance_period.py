# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ItvAttendancePeriod(models.Model):
    _name = 'itv.attendance.period'
    _inherit = ['itv.audit.mixin']
    _description = "Période de pointage"
    _order = 'month desc'
    _rec_name = 'month'

    company_id = fields.Many2one('res.company', string="Société", required=True, default=lambda self: self.env.company)
    month = fields.Date("Mois", required=True, help="Premier jour du mois concerné.")
    state = fields.Selection([('open', "Ouverte"), ('closed', "Clôturée")], string="État", required=True,
                             default='open', tracking=True)
    closed_uid = fields.Many2one('res.users', string="Clôturée par", readonly=True)
    closed_date = fields.Datetime("Clôturée le", readonly=True)
    skipped_count = fields.Integer("Modifications ignorées", readonly=True,
                                   help="Pointages arrivés après la clôture : leurs journées n'ont pas été recalculées.")
    note = fields.Char("Remarque")

    _company_month_uniq = models.UniqueIndex('(company_id, month)', "Cette période existe déjà pour cette société.")

    @api.model
    def _get(self, company, month):
        period = self.sudo().search([('company_id', '=', company.id), ('month', '=', month)], limit=1)
        return period or self.sudo().create({'company_id': company.id, 'month': month})

    def action_close(self):
        self.write({'state': 'closed', 'closed_uid': self.env.uid, 'closed_date': fields.Datetime.now(), 'skipped_count': 0})

    def action_open(self):
        self.write({'state': 'open', 'closed_uid': False, 'closed_date': False})

    def action_recompute(self):
        """Recalcule le mois d'une période rouverte : à lancer après une clôture levée."""
        self.ensure_one()
        if self.state == 'closed':
            raise UserError(_("Rouvrez la période avant de la recalculer."))
        employees = self.env['hr.employee'].sudo().with_context(active_test=False).search([('company_id', '=', self.company_id.id)])
        self.env['itv.attendance.dirty']._enqueue_from_punches(employees.ids, month=self.month)
        self.env.ref('itv_zk_attendance.ir_cron_itv_attendance_recompute').sudo()._trigger()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': 'info', 'title': _("Recalcul lancé"), 'message': _("Les journées du mois seront recalculées en arrière-plan.")},
        }

