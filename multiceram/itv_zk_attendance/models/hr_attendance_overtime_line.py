# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError

ITV_STATES = [
    ('submitted', "En cours de validation"),
    ('validated_1', "Validée N1"),
    ('validated_2', "Validée N2"),
    ('refused', "Refusée"),
]
# Heures déclarées : elles entrent dans les totaux du calcul historique tant qu'elles ne sont pas refusées.
DECLARED_STATES = ('submitted', 'validated_1', 'validated_2')
ITV_RATES = [('25', "25 %"), ('50', "50 %"), ('100', "100 %")]
RATE_AMOUNTS = {'25': 1.25, '50': 1.5, '100': 2.0}
NATIVE_STATUS = {
    'submitted': 'to_approve',
    'validated_1': 'to_approve',
    'validated_2': 'approved',
    'refused': 'refused',
}
LOCKED_FIELDS = {'employee_id', 'date', 'duration', 'manual_duration', 'itv_rate', 'amount_rate'}
WORKFLOW_FIELDS = {'itv_state', 'status'}
RECOMPUTE_FIELDS = {'employee_id', 'date', 'duration', 'itv_rate', 'itv_state'}
STEPS = ('itv_validated_1', 'itv_validated_2', 'itv_refused')


class HrAttendanceOvertimeLine(models.Model):
    _inherit = 'hr.attendance.overtime.line'

    itv_day_id = fields.Many2one('itv.attendance.day', string="Journée de pointage", readonly=True, copy=False,
                                 index='btree_not_null', ondelete='set null')
    itv_state = fields.Selection(ITV_STATES, string="Statut", copy=False, index='btree_not_null',
                                 help="Étape de validation MultiCeram ; vide pour les heures supplémentaires natives.")
    itv_rate = fields.Selection(ITV_RATES, string="Taux")
    itv_submitted_uid = fields.Many2one('res.users', string="Demandée par", readonly=True, copy=False)
    itv_submitted_date = fields.Datetime("Demandée le", readonly=True, copy=False)
    itv_validated_1_uid = fields.Many2one('res.users', string="Validée N1 par", readonly=True, copy=False)
    itv_validated_1_date = fields.Datetime("Validée N1 le", readonly=True, copy=False)
    itv_validated_2_uid = fields.Many2one('res.users', string="Validée N2 par", readonly=True, copy=False)
    itv_validated_2_date = fields.Datetime("Validée N2 le", readonly=True, copy=False)
    itv_refused_uid = fields.Many2one('res.users', string="Refusée par", readonly=True, copy=False)
    itv_refused_date = fields.Datetime("Refusée le", readonly=True, copy=False)

    _itv_rate_uniq = models.UniqueIndex("(employee_id, date, itv_rate) WHERE itv_state IS NOT NULL",
                                        "Une seule ligne d'heures supplémentaires par employé, jour et taux.")

    @api.model_create_multi
    def create(self, vals_list):
        Day = self.env['itv.attendance.day'].sudo()
        for vals in vals_list:
            state = vals.get('itv_state') or self.env.context.get('default_itv_state')
            if not state:
                continue
            rate = vals.get('itv_rate') or self.env.context.get('default_itv_rate')
            vals.update(itv_state=state, status=NATIVE_STATUS[state])
            vals.setdefault('itv_submitted_uid', self.env.uid)
            vals.setdefault('itv_submitted_date', fields.Datetime.now())
            if rate:
                vals.update(itv_rate=rate, amount_rate=RATE_AMOUNTS[rate])
            if not vals.get('itv_day_id') and vals.get('employee_id') and vals.get('date'):
                day = Day.search([('employee_id', '=', vals['employee_id']), ('date', '=', vals['date'])], limit=1)
                attendance = day.attendance_ids[:1]
                vals['itv_day_id'] = day.id or False
                vals.setdefault('time_start', attendance.check_in or False)
                vals.setdefault('time_stop', attendance.check_out or False)
        lines = super().create(vals_list)
        nabi = lines.filtered('itv_state')
        if nabi:
            nabi._itv_enqueue()
            nabi._itv_refresh_attendances()
        return lines

    def write(self, vals):
        nabi = self.filtered('itv_state')
        if nabi and not self.env.context.get('itv_overtime_sync'):
            if WORKFLOW_FIELDS & set(vals):
                raise UserError(_("Le circuit des heures supplémentaires se gère avec ses boutons : validations, refus."))
            if LOCKED_FIELDS & set(vals) and nabi.filtered(lambda line: line.itv_state != 'submitted'):
                raise UserError(_("Ces heures supplémentaires sont déjà validées ou refusées : remettez-les en validation pour les modifier."))
        vals = dict(vals)
        if vals.get('itv_rate'):
            vals['amount_rate'] = RATE_AMOUNTS[vals['itv_rate']]
        if vals.get('itv_state'):
            vals['status'] = NATIVE_STATUS[vals['itv_state']]
        recompute = bool(RECOMPUTE_FIELDS & set(vals))
        before = nabi._itv_employee_dates() if recompute else []
        result = super().write(vals)
        if recompute:
            self.filtered('itv_state')._itv_enqueue(before)
        return result

    def unlink(self):
        # Odoo supprime puis régénère les heures supplémentaires à chaque modification de présence : on garde celles du circuit.
        lines = self.filtered(lambda line: not line.itv_state) if self.env.context.get('itv_keep_overtime') else self
        nabi = lines.filtered('itv_state')
        if nabi.filtered(lambda line: line.itv_state not in ('submitted', 'refused')) and not self.env.context.get('itv_overtime_sync'):
            raise UserError(_("Seules les heures supplémentaires en cours de validation ou refusées peuvent être supprimées."))
        pairs = nabi._itv_employee_dates()
        attendances = nabi.sudo()._linked_attendances()
        result = super(HrAttendanceOvertimeLine, lines).unlink()
        if nabi:
            self.env['itv.attendance.dirty']._enqueue(pairs)
            self.browse()._itv_refresh_attendances(attendances)
        return result

    # -- Boutons natifs de Présences : ils suivent le circuit ---------------------------------------

    def action_approve(self):
        nabi = self.filtered('itv_state')
        for lines in nabi._itv_day_lines().grouped(lambda line: (line.employee_id, line.date)).values():
            if lines[0].itv_state == 'submitted':
                lines.action_itv_validate_1()
            elif lines[0].itv_state == 'validated_1':
                lines.action_itv_validate_2()
            else:
                raise UserError(_("Ces heures supplémentaires ne sont pas en attente de validation."))
        return super(HrAttendanceOvertimeLine, self - nabi).action_approve()

    def action_refuse(self):
        nabi = self.filtered('itv_state')
        if nabi:
            nabi.action_itv_refuse()
        return super(HrAttendanceOvertimeLine, self - nabi).action_refuse()

    # -- Circuit de validation ---------------------------------------------------------------------

    def action_itv_validate_1(self):
        self._itv_check_group('itv_zk_attendance.group_itv_overtime_validation_1')
        lines = self._itv_day_lines()
        lines._itv_check_states(('submitted',), _("Seules les heures supplémentaires en cours de validation peuvent être validées au niveau 1."))
        lines._itv_step('validated_1', 'itv_validated_1')

    def action_itv_validate_2(self):
        self._itv_check_group('itv_zk_attendance.group_itv_overtime_validation_2')
        lines = self._itv_day_lines()
        lines._itv_check_states(('validated_1',), _("Seules les heures supplémentaires validées au niveau 1 peuvent être validées au niveau 2."))
        if not self._itv_separation_exempt() and lines.filtered(lambda line: line.itv_validated_1_uid == self.env.user):
            raise UserError(_("La validation de niveau 2 doit être faite par une autre personne que la validation de niveau 1."))
        lines._itv_step('validated_2', 'itv_validated_2')

    def _itv_separation_exempt(self):
        """Recette : le compte Administrateur peut enchaîner N1 puis N2 pour dérouler le circuit seul.

        La séparation des validateurs reste imposée à tout le monde d'autre. À retirer le jour où
        deux comptes de validation existent chez le client.
        """
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        return self.env.user.id == SUPERUSER_ID or (admin and self.env.user == admin)

    def action_itv_refuse(self):
        self._itv_check_group('itv_zk_attendance.group_itv_overtime_validation_1')
        lines = self._itv_day_lines()
        lines._itv_check_states(('submitted', 'validated_1'), _("Seules les heures supplémentaires en cours de validation peuvent être refusées."))
        lines._itv_step('refused', 'itv_refused')

    def action_itv_reset(self):
        """Remet la journée en cours de validation : correction d'un refus ou d'une validation à revoir."""
        lines = self._itv_day_lines()
        lines._itv_check_states(('validated_1', 'refused'), _("Seules les heures supplémentaires validées au niveau 1, ou refusées, peuvent être remises en validation."))
        vals = {'itv_state': 'submitted'}
        for step in STEPS:
            vals.update({step + '_uid': False, step + '_date': False})
        lines.sudo().with_context(itv_overtime_sync=True).write(vals)

    def _itv_day_lines(self):
        """Le circuit porte sur la journée : toutes les lignes (tous taux) du même employé et du même jour."""
        nabi = self.filtered('itv_state')
        if not nabi:
            return nabi
        pairs = {(line.employee_id.id, line.date) for line in nabi}
        candidates = self.search([
            ('itv_state', '!=', False),
            ('employee_id', 'in', list({employee_id for employee_id, _day in pairs})),
            ('date', 'in', list({day for _employee_id, day in pairs})),
        ])
        return candidates.filtered(lambda line: (line.employee_id.id, line.date) in pairs)

    def _itv_check_states(self, states, message):
        if not self or self.filtered(lambda line: line.itv_state not in states):
            raise UserError(message)

    def _itv_check_group(self, xmlid):
        if not self.env.user.has_group(xmlid):
            raise AccessError(_("Vous n'avez pas le droit de valider ces heures supplémentaires à ce niveau."))

    def _itv_step(self, state, prefix):
        self.sudo().with_context(itv_overtime_sync=True).write({
            'itv_state': state,
            prefix + '_uid': self.env.uid,
            prefix + '_date': fields.Datetime.now(),
        })

    def _itv_employee_dates(self):
        return [(line.employee_id.id, line.date) for line in self]

    def _itv_enqueue(self, extra=()):
        self.env['itv.attendance.dirty']._enqueue(self._itv_employee_dates() + list(extra))

    def _itv_refresh_attendances(self, attendances=None):
        attendances = self.sudo()._linked_attendances() | (attendances or self.env['hr.attendance'].sudo())
        for name in ('overtime_hours', 'overtime_status', 'validated_overtime_hours'):
            self.env.add_to_compute(attendances._fields[name], attendances)
