# -*- coding: utf-8 -*-
from odoo import _, api, fields, models

LEGACY_SETTINGS = ('itv_schedule_type', 'itv_day_hours', 'itv_week_hours', 'itv_auto_pause', 'itv_ignore_uhf')
PROFILE_FIELDS = {'itv_schedule_type', 'itv_week_hours'}


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    itv_schedule_type = fields.Selection(
        [('normal', "Normal"), ('poste', "Poste (3x8)"), ('securite', "Sécurité")],
        string="Horaire", groups='hr.group_hr_user',
        help="Seul l'horaire « Normal » applique les règles du samedi et du dimanche du calcul historique.")
    itv_day_hours = fields.Float("Heures par jour", groups='hr.group_hr_user',
                                 help="Norme journalière du calcul historique ; vide = 8 h.")
    itv_week_hours = fields.Integer("Heures par semaine", groups='hr.group_hr_user',
                                    help="44 : le samedi compte 4 h pour l'horaire « Normal ».")
    itv_auto_pause = fields.Boolean("Pause automatique", groups='hr.group_hr_user',
                                    help="Déduit toujours une heure de pause dans le calcul historique.")
    itv_overtime_eligible = fields.Boolean("Heures supplémentaires autorisées", groups='hr.group_hr_user')
    itv_ignore_uhf = fields.Boolean("Ignorer la barrière UHF", groups='hr.group_hr_user',
                                    help="Les passages de la barrière UHF (CVSecurity) sortent de son calcul.")

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        profiled = [employee.id for employee, vals in zip(employees, vals_list) if PROFILE_FIELDS & set(vals)]
        self.browse(profiled)._itv_apply_profile_calendar()
        return employees

    def write(self, vals):
        result = super().write(vals)
        if PROFILE_FIELDS & set(vals) and not self.env.context.get('itv_skip_profile_calendar'):
            self._itv_apply_profile_calendar()
        if set(vals) & set(LEGACY_SETTINGS) and not self.env.context.get('itv_skip_legacy_enqueue'):
            self.env['itv.attendance.dirty']._enqueue_from_punches(self.ids)
        return result

    def _itv_profile_calendar(self):
        """Horaire de travail natif des réglages nabi_hr : poste et sécurité flexibles, sinon la règle du samedi (44 h ou non)."""
        self.ensure_one()
        if self.itv_schedule_type in ('poste', 'securite'):
            xmlid = 'resource_calendar_%s' % self.itv_schedule_type
        else:
            xmlid = 'resource_calendar_normal_44' if self.itv_week_hours == 44 else 'resource_calendar_normal_48'
        return self.env.ref('itv_zk_attendance.%s' % xmlid, raise_if_not_found=False)

    def _itv_apply_profile_calendar(self):
        changed = self.browse()
        for employee in self.sudo():
            calendar = employee._itv_profile_calendar()
            if calendar and employee.resource_calendar_id != calendar:
                employee.with_context(tracking_disable=True, itv_skip_profile_calendar=True).resource_calendar_id = calendar
                changed |= employee
        return changed

    def action_itv_apply_profile_calendar(self):
        changed = self._itv_apply_profile_calendar()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Horaire de travail"),
                'message': _("%s employé(s) mis à jour selon leur profil de pointage.", len(changed)),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_itv_recompute_legacy(self):
        self.env['itv.attendance.dirty']._enqueue_from_punches(self.ids)
        self.env.ref('itv_zk_attendance.ir_cron_itv_attendance_recompute').sudo()._trigger()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'info',
                'title': _("Recalcul lancé"),
                'message': _("Les journées seront recalculées en arrière-plan."),
            },
        }
