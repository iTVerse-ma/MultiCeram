# -*- coding: utf-8 -*-
"""Planning des horaires : quel horaire s'applique à quel employé, et quand.

Odoo range l'horaire de travail sur le contrat : en changer chaque semaine réécrirait
l'historique contractuel. Ce planning pose l'horaire par période, sans y toucher, et
l'applique à la fiche tant qu'il court.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ItvEmployeeShift(models.Model):
    _name = 'itv.employee.shift'
    _inherit = ['itv.audit.mixin']
    _description = "Horaire planifié d'un employé"
    _order = 'date_from desc, id desc'
    _rec_name = 'calendar_id'

    employee_id = fields.Many2one('hr.employee', string="Employé", required=True, ondelete='cascade', index=True)
    calendar_id = fields.Many2one('resource.calendar', string="Horaire", required=True,
                                  ondelete='restrict', tracking=True, domain="[('itv_is_shift', '=', True)]")
    date_from = fields.Date("Du", required=True, default=fields.Date.context_today, tracking=True)
    date_to = fields.Date("Au", tracking=True, help="Vide : l'horaire s'applique jusqu'à nouvel ordre.")
    company_id = fields.Many2one(related='employee_id.company_id', store=True, index=True)
    note = fields.Char("Note")

    @api.constrains('employee_id', 'date_from', 'date_to')
    def _check_overlap(self):
        for record in self:
            if record.date_to and record.date_to < record.date_from:
                raise ValidationError(_("La fin de période précède son début pour %s.",
                                        record.employee_id.display_name))
            clash = self.search([
                ('id', '!=', record.id),
                ('employee_id', '=', record.employee_id.id),
                ('date_from', '<=', record.date_to or '9999-12-31'),
                '|', ('date_to', '=', False), ('date_to', '>=', record.date_from),
            ], limit=1)
            if clash:
                raise ValidationError(_(
                    "%(employee)s suit déjà l'horaire « %(calendar)s » du %(start)s au %(end)s : "
                    "les périodes ne peuvent pas se chevaucher.",
                    employee=record.employee_id.display_name, calendar=clash.calendar_id.name,
                    start=clash.date_from, end=clash.date_to or _("nouvel ordre")))

    def _itv_enqueue_days(self):
        """Remet en file les journées couvertes : leurs chiffres dépendent de l'horaire."""
        today = fields.Date.context_today(self)
        pairs = []
        for record in self:
            day, last = record.date_from, min(record.date_to or today, today)
            while day <= last:
                pairs.append((record.employee_id.id, day))
                day += timedelta(days=1)
        if pairs:
            self.env['itv.attendance.dirty']._enqueue(pairs)

    def _itv_apply_calendar(self):
        """Pose l'horaire de la période en cours sur la fiche de l'employé."""
        today = fields.Date.context_today(self)
        for record in self:
            if record.date_from > today or (record.date_to and record.date_to < today):
                continue
            employee = record.employee_id.sudo()
            if employee.resource_calendar_id != record.calendar_id:
                employee.with_context(itv_skip_profile_calendar=True).resource_calendar_id = record.calendar_id

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._itv_enqueue_days()
        records._itv_apply_calendar()
        for record in records:
            record._itv_audit(_("Horaire planifié"), [
                _("Employé : %s", record.employee_id.display_name),
                _("Horaire : %s", record.calendar_id.display_name),
                _("Période : du %(start)s au %(end)s", start=record.date_from,
                  end=record.date_to or _("nouvel ordre")),
            ])
        return records

    def write(self, vals):
        self._itv_enqueue_days()        # ancienne période
        result = super().write(vals)
        self._itv_enqueue_days()        # nouvelle période
        self._itv_apply_calendar()
        return result

    def unlink(self):
        self._itv_enqueue_days()
        return super().unlink()

    @api.model
    def _calendar_for(self, employee, day):
        """Horaire applicable à une journée : le planning d'abord, puis la fiche de l'employé."""
        planned = self.sudo().search([
            ('employee_id', '=', employee.id),
            ('date_from', '<=', day),
            '|', ('date_to', '=', False), ('date_to', '>=', day),
        ], limit=1)
        return planned.calendar_id or employee.sudo().resource_calendar_id

    @api.model
    def _calendars_for_range(self, employee, start, end):
        """{jour: horaire} sur une période, planning et fiche confondus."""
        default = employee.sudo().resource_calendar_id
        plans = self.sudo().search([
            ('employee_id', '=', employee.id),
            ('date_from', '<=', end),
            '|', ('date_to', '=', False), ('date_to', '>=', start),
        ])
        calendars, day = {}, start
        while day <= end:
            match = next((plan.calendar_id for plan in plans
                          if plan.date_from <= day and (not plan.date_to or plan.date_to >= day)), default)
            if match:
                calendars[day] = match
            day += timedelta(days=1)
        return calendars
