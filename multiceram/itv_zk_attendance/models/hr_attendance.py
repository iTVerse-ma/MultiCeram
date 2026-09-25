# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models

from .attendance_day import WEEKDAYS


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    itv_day_id = fields.Many2one('itv.attendance.day', string="Journée de pointage", readonly=True, copy=False,
                                 index='btree_not_null', ondelete='cascade')
    itv_is_marker = fields.Boolean(
        "Journée sans présence", readonly=True, copy=False,
        help="Journée sans pointage exploitable (absence, pointage impair, calcul impossible) : repère d'une seconde "
             "pour garder une ligne par jour.")

    # Chiffres du calcul historique (règles nabi_hr) rattachés à la journée.
    itv_weekday = fields.Selection(related='itv_day_id.weekday', string="Jour de la semaine")
    itv_day_label = fields.Char("Jour", compute='_compute_itv_day_label',
                                help="Aujourd'hui, Hier, ou le jour de la semaine.")

    @api.depends('date')
    def _compute_itv_day_label(self):
        today = fields.Date.context_today(self)
        weekdays = dict(WEEKDAYS)
        for attendance in self:
            date = attendance.date
            if not date:
                attendance.itv_day_label = False
            elif date == today:
                attendance.itv_day_label = _("Aujourd'hui")
            elif date == today - timedelta(days=1):
                attendance.itv_day_label = _("Hier")
            else:
                attendance.itv_day_label = weekdays.get(str(date.weekday()))
    itv_punch_summary = fields.Char(related='itv_day_id.punch_summary', string="Pointages")
    itv_first_punch = fields.Char(related='itv_day_id.first_punch_label', string="Premier pointage")
    itv_last_punch = fields.Char(related='itv_day_id.last_punch_label', string="Dernier pointage")
    itv_punch_count = fields.Integer(related='itv_day_id.lg_punch_count', string="Nombre de pointages")
    itv_heures = fields.Float(related='itv_day_id.lg_heures', string="H.Prés", store=True)
    itv_heures25 = fields.Float(related='itv_day_id.lg_heures25', string="H.Nor", store=True)
    itv_pause = fields.Float(related='itv_day_id.lg_pause', string="Pause", store=True)
    itv_abs25 = fields.Float(related='itv_day_id.lg_abs25', string="Abs.", store=True)
    itv_hs = fields.Float(related='itv_day_id.lg_hs', string="HS", store=True)
    itv_hs25 = fields.Float(related='itv_day_id.lg_hs25', string="HS corr.", store=True)
    itv_hs50 = fields.Float(related='itv_day_id.lg_hs50', string="HS dimanche", store=True)
    itv_overtime_hours = fields.Float(related='itv_day_id.overtime_hours', string="HS circuit", store=True)
    itv_overtime_state = fields.Selection(related='itv_day_id.overtime_state', string="Validation HS", store=True)
    itv_anomaly_state = fields.Selection(related='itv_day_id.anomaly_state', string="Anomalie", store=True)
    itv_anomaly_label = fields.Char(related='itv_day_id.anomaly_label', string="Type d'anomalie")
    itv_anomaly_note = fields.Char(related='itv_day_id.anomaly_note', string="Motif de l'anomalie")
    itv_has_leave = fields.Boolean(related='itv_day_id.has_leave', string="Congé", store=True)
    itv_is_holiday = fields.Boolean(related='itv_day_id.is_holiday', string="JF", store=True)
    itv_is_rest_day = fields.Boolean(related='itv_day_id.is_rest_day', string="JR", store=True)
    itv_error = fields.Selection(related='itv_day_id.lg_error', string="Calcul impossible", store=True)

    # -- Correction manuelle : la valeur saisie l'emporte, le calcul reste visible à côté --------
    itv_manual_override = fields.Boolean(
        "Corrigée", readonly=True, copy=False,
        help="Heures saisies à la main : le recalcul ne les écrase plus, il met seulement à jour les heures calculées.")
    itv_computed_check_in = fields.Datetime("Arrivée calculée", readonly=True, copy=False)
    itv_computed_check_out = fields.Datetime("Départ calculé", readonly=True, copy=False)
    itv_override_differs = fields.Boolean(
        "Écart avec le calcul", compute='_compute_itv_override_differs', store=True,
        help="La correction manuelle ne donne pas les mêmes heures que le calcul historique.")

    @api.depends('itv_manual_override', 'check_in', 'check_out', 'itv_computed_check_in', 'itv_computed_check_out')
    def _compute_itv_override_differs(self):
        for attendance in self:
            attendance.itv_override_differs = bool(
                attendance.itv_manual_override
                and (attendance.check_in, attendance.check_out)
                != (attendance.itv_computed_check_in, attendance.itv_computed_check_out))

    @api.model_create_multi
    def create(self, vals_list):
        """Présence saisie à la main : elle rejoint sa journée de pointage et y fait foi.

        Sans ce rattachement, le recalcul de la journée en créerait une seconde à côté, et
        l'écran signalerait une présence non reportée.
        """
        attendances = super().create(vals_list)
        if self.env.context.get('itv_attendance_sync'):
            return attendances
        Day = self.env['itv.attendance.day'].sudo()
        for attendance in attendances.filtered(lambda record: not record.itv_day_id and record.check_in):
            day = Day._itv_day_for(attendance.employee_id, attendance.check_in)
            if not day:
                continue
            attendance.with_context(itv_attendance_sync=True).write({
                'itv_day_id': day.id, 'itv_manual_override': True,
            })
            attendance._itv_audit(_("Présence saisie à la main"), [
                _("Employé : %s", attendance.employee_id.display_name),
                _("Journée : %s", day.date),
                _("Arrivée : %s", attendance.check_in),
                _("Départ : %s", attendance.check_out or _("en cours")),
                _("Le recalcul des pointages ne l'écrasera pas."),
            ])
        return attendances

    def write(self, vals):
        corrected = self.filtered('itv_day_id') if (
            not self.env.context.get('itv_attendance_sync') and {'check_in', 'check_out'} & set(vals)) else self.browse()
        if corrected:
            vals = dict(vals, itv_manual_override=True)
            for attendance in corrected.filtered(lambda line: not line.itv_computed_check_in):
                # Première correction : les heures calculées sont celles que la ligne porte encore.
                super(HrAttendance, attendance).write(
                    {'itv_computed_check_in': attendance.check_in, 'itv_computed_check_out': attendance.check_out})
        return super().write(vals)

    def _itv_store_computed(self, vals):
        """Garde les heures calculées à côté de la correction manuelle, sans toucher à celle-ci."""
        self.ensure_one()
        if (self.itv_computed_check_in, self.itv_computed_check_out) != (vals['check_in'], vals['check_out']):
            self.write({'itv_computed_check_in': vals['check_in'], 'itv_computed_check_out': vals['check_out']})

    def action_itv_drop_override(self):
        """Reprend les heures calculées : la correction manuelle est abandonnée."""
        corrected = self.filtered('itv_manual_override')
        corrected.sudo().with_context(itv_attendance_sync=True).write({'itv_manual_override': False})
        for employee, attendances in corrected.grouped('employee_id').items():
            dates = attendances.mapped('itv_day_id.date')
            self.env['itv.attendance.day'].sudo()._sync_attendances(employee.sudo(), min(dates), max(dates))
        return True

    def _update_overtime(self, attendance_domain=None):
        return super(HrAttendance, self.with_context(itv_keep_overtime=True))._update_overtime(attendance_domain)

    # -- Actions de la journée, appelées depuis la liste des présences -----------------------------

    def action_itv_open_punches(self):
        return self.itv_day_id.action_open_punches()

    def action_itv_add_punch(self):
        return self.itv_day_id.action_add_punch()

    def action_itv_new_leave(self):
        return self.itv_day_id.action_new_leave()

    def action_itv_toggle_rest_day(self):
        return self.itv_day_id.action_toggle_rest_day()

    def action_itv_propose_overtime(self):
        return self.itv_day_id.action_propose_overtime()

    def action_itv_recompute(self):
        return self.itv_day_id.action_recompute_days()

    def action_itv_reopen_anomaly(self):
        return self.itv_day_id.action_reopen_anomaly()
