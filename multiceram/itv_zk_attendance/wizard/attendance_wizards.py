# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.addons.itv_zk_connector.services.timeutils import format_local, utc_to_local

# Valeurs du formulaire « Add Manual Punch » de nabi_hr, envoyées telles quelles à l'API BioTime (à confirmer en phase B).
PUNCH_STATES = [('1', "Entrée"), ('2', "Sortie")]


class ItvAttendanceAnomalyWizard(models.TransientModel):
    _name = 'itv.attendance.anomaly.wizard'
    _description = "Traitement des anomalies de pointage"

    def _default_day_ids(self):
        """Sélection venant des journées ou des présences (la liste des présences porte les mêmes actions)."""
        context = self.env.context
        records = self.env[context.get('active_model', 'itv.attendance.day')].browse(context.get('active_ids', []))
        days = records if records._name == 'itv.attendance.day' else records.itv_day_id
        return days.filtered('anomaly_state')

    day_ids = fields.Many2many('itv.attendance.day', string="Journées", default=_default_day_ids)
    resolution = fields.Selection([('justified', "Justifier"), ('ignored', "Ignorer")], string="Traitement",
                                  required=True, default='justified')
    note = fields.Char("Motif")

    def action_apply(self):
        self.ensure_one()
        days = self.day_ids.filtered('anomaly_state')
        if not days:
            raise UserError(_("Aucune journée sélectionnée n'a d'anomalie."))
        days.check_access('read')
        days.sudo().write({'anomaly_resolution': self.resolution, 'anomaly_note': self.note or False})
        return {'type': 'ir.actions.act_window_close'}


class ItvAttendancePunchWizard(models.TransientModel):
    _name = 'itv.attendance.punch.wizard'
    _description = "Ajout d'un pointage manuel"

    day_id = fields.Many2one('itv.attendance.day', string="Journée", required=True, ondelete='cascade')
    employee_id = fields.Many2one(related='day_id.employee_id', string="Employé")
    punch_time = fields.Datetime("Heure du pointage", required=True)
    punch_state = fields.Selection(PUNCH_STATES, string="Sens", required=True, default='1')
    reason = fields.Char("Motif")

    def action_confirm(self):
        """Pointage ajouté dans Odoo, mis en file d'envoi vers BioTime (pointage manuel + approbation, comme nabi_hr)."""
        self.ensure_one()
        day = self.day_id
        day.check_access('read')
        employee = day.employee_id.sudo()
        backend, tz = day._backend_timezone()
        if not backend:
            raise UserError(_("Aucune connexion BioTime n'est déclarée pour la société de %s.", employee.name))
        local = utc_to_local(self.punch_time, tz)
        punch = self.env['itv.zk.punch'].sudo().create({
            'backend_id': backend.id,
            'source': 'odoo_manual',
            'emp_code': employee.barcode or False,
            'employee_id': employee.id,
            'punch_local': format_local(local),
            'punch_time': self.punch_time,
            'punch_date': local.date(),
            'punch_state': self.punch_state,
        })
        self.env['itv.zk.outbox'].sudo().create({
            'backend_id': backend.id,
            'operation': 'manuallog',
            'payload': {
                'employee': employee.itv_biotime_emp_id or False,
                'emp_code': employee.barcode or False,
                'punch_time': format_local(local),
                'punch_state': self.punch_state,
                'apply_reason': self.reason or '',
            },
            'res_model': 'itv.zk.punch',
            'res_id': punch.id,
        })
        punch._on_punches_imported()
        # La journée du pointage et celle de la ligne, plus leurs veilles (report de nuit).
        dates = {local.date(), day.date}
        dates |= {date - timedelta(days=1) for date in set(dates)}
        self.env['itv.attendance.day'].sudo()._recompute_days(employee, sorted(dates))
        return {'type': 'ir.actions.act_window_close'}
