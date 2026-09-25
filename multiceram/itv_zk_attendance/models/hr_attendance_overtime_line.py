# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

ITV_STATES = [
    ('submitted', "Détectées par le système"),
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
    # itv.audit.mixin apporte la discussion : sans elle, `tracking=True` et `_itv_audit` n'ont pas de support.
    _name = 'hr.attendance.overtime.line'
    _inherit = ['hr.attendance.overtime.line', 'itv.audit.mixin']

    itv_day_id = fields.Many2one('itv.attendance.day', string="Journée de pointage", readonly=True, copy=False,
                                 index='btree_not_null', ondelete='set null')
    # group_expand : les quatre étapes restent affichées même vides, pour voir d'un coup ce qui manque.
    itv_state = fields.Selection(ITV_STATES, string="Statut", copy=False, index='btree_not_null', tracking=True,
                                 group_expand=True,
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

    # Le circuit suit l'organigramme : N1 = responsable de l'employé, N2 = responsable du N1.
    itv_validator_1_id = fields.Many2one(
        'res.users', string="Valideur N1", compute='_compute_itv_validators', store=True,
        help="Utilisateur du responsable direct de l'employé, d'après l'organigramme.")
    itv_validator_2_id = fields.Many2one(
        'res.users', string="Valideur N2", compute='_compute_itv_validators', store=True,
        help="Utilisateur du responsable du N1, d'après l'organigramme.")
    itv_system_hours = fields.Float(
        "Heures détectées", compute='_compute_itv_system_hours', store=True, readonly=True,
        help="Heures supplémentaires calculées à partir des pointages pour cette journée et ce taux. "
             "Elles plafonnent ce qui peut être validé : personne n'accorde plus que ce que la pointeuse a vu.")
    itv_can_validate_1 = fields.Boolean(compute='_compute_itv_can_act')
    itv_can_validate_2 = fields.Boolean(compute='_compute_itv_can_act')
    itv_can_refuse = fields.Boolean(compute='_compute_itv_can_act')
    itv_can_reset = fields.Boolean(compute='_compute_itv_can_act')

    @api.depends('itv_day_id.lg_hs25', 'itv_day_id.lg_hs50', 'itv_rate')
    def _compute_itv_system_hours(self):
        for line in self:
            day = line.itv_day_id
            if not day or not line.itv_state:
                line.itv_system_hours = 0.0
            elif line.itv_rate == '50':
                line.itv_system_hours = day.lg_hs50
            elif line.itv_rate == '25':
                line.itv_system_hours = day.lg_hs25
            else:
                # Taux 100 % : jamais issu du calcul, il vient d'une décision (jour férié, requalification).
                line.itv_system_hours = 0.0

    @api.constrains('duration', 'itv_rate')
    def _check_itv_system_cap(self):
        """Personne ne saisit plus d'heures que ce que les pointages montrent.

        Le plafond ne s'applique qu'aux journées où le calcul a trouvé des heures : une journée
        sans détection (anomalie requalifiée, saisie à la main) n'aurait sinon aucune HS possible.
        Il porte sur ce qu'on saisit, pas sur l'historique : un recalcul qui ferait baisser les
        heures détectées ne rend pas invalides des lignes déjà validées.
        """
        for line in self.filtered(lambda l: l.itv_state and l.itv_system_hours > 0):
            if line.duration > line.itv_system_hours + 1e-4:
                raise ValidationError(_(
                    "%(employee)s, %(date)s : %(asked)s demandées pour %(detected)s détectées par les pointages. "
                    "On ne peut pas valider plus que ce que la pointeuse a enregistré.",
                    employee=line.employee_id.display_name, date=line.date,
                    asked=("%02d:%02d" % (int(line.duration), round(line.duration % 1 * 60))),
                    detected=("%02d:%02d" % (int(line.itv_system_hours), round(line.itv_system_hours % 1 * 60)))))

    @api.depends('employee_id.parent_id.user_id', 'employee_id.parent_id.parent_id.user_id')
    def _compute_itv_validators(self):
        for line in self:
            manager = line.employee_id.parent_id
            line.itv_validator_1_id = manager.user_id
            line.itv_validator_2_id = manager.parent_id.user_id

    def _compute_itv_can_act(self):
        """Boutons visibles pour la seule personne dont c'est le tour."""
        user, exempt = self.env.user, self._itv_separation_exempt()
        for line in self:
            is_1 = exempt or line.itv_validator_1_id == user
            is_2 = exempt or line.itv_validator_2_id == user
            line.itv_can_validate_1 = line.itv_state == 'submitted' and is_1
            line.itv_can_validate_2 = line.itv_state == 'validated_1' and is_2
            # Le N2 peut refuser ce qu'il a lui-même accepté : sa décision reste la sienne.
            line.itv_can_refuse = ((line.itv_state in ('submitted', 'validated_1') and (is_1 or is_2))
                                   or (line.itv_state == 'validated_2' and is_2))
            line.itv_can_reset = line.itv_state in ('validated_1', 'refused') and (is_1 or is_2)

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
        """Bouton « Valider » de l'entête : chaque journée avance d'une étape, N1 puis N2.

        Les lignes déjà traitées (validées N2, refusées) sont ignorées : une sélection peut en
        contenir, en particulier depuis l'écran des heures supplémentaires traitées. On ne
        prévient que si rien du tout n'était à valider.
        """
        nabi = self.filtered('itv_state')
        groups = nabi._itv_day_lines().grouped(lambda line: (line.employee_id, line.date))
        pending = [lines for lines in groups.values() if lines[0].itv_state in ('submitted', 'validated_1')]
        if nabi and not pending:
            raise UserError(_("Aucune des heures supplémentaires sélectionnées n'est en attente de validation."))
        for lines in pending:
            if lines[0].itv_state == 'submitted':
                lines.action_itv_validate_1()
            else:
                lines.action_itv_validate_2()
        return super(HrAttendanceOvertimeLine, self - nabi).action_approve()

    def action_refuse(self):
        nabi = self.filtered('itv_state')
        if nabi:
            nabi.action_itv_refuse()
        return super(HrAttendanceOvertimeLine, self - nabi).action_refuse()

    # -- Circuit de validation ---------------------------------------------------------------------

    def action_itv_validate_1(self):
        lines = self._itv_day_lines()
        lines._itv_check_validator(1)
        lines._itv_check_states(('submitted',), _("Seules les heures supplémentaires en cours de validation peuvent être validées au niveau 1."))
        lines._itv_step('validated_1', 'itv_validated_1')

    def action_itv_validate_2(self):
        lines = self._itv_day_lines()
        lines._itv_check_validator(2)
        lines._itv_check_states(('validated_1',), _("Seules les heures supplémentaires validées au niveau 1 peuvent être validées au niveau 2."))
        if not self._itv_separation_exempt() and lines.filtered(lambda line: line.itv_validated_1_uid == self.env.user):
            raise UserError(_("La validation de niveau 2 doit être faite par une autre personne que la validation de niveau 1."))
        lines._itv_step('validated_2', 'itv_validated_2')

    def _itv_separation_exempt(self):
        """Recette : le compte Administrateur agit à tous les niveaux pour dérouler le circuit seul.

        Tout le monde d'autre suit l'organigramme, N1 puis N2, par deux personnes différentes.
        À retirer le jour où les responsables du client sont en place.
        """
        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        return self.env.user.id == SUPERUSER_ID or (admin and self.env.user == admin)

    def action_itv_refuse(self):
        """Refuse les journées : avant la décision du N2, ou après, s'il revient dessus.

        Le N1 refuse ce qui est encore détecté ; le N2 refuse ce que le N1 a validé, et peut aussi
        revenir sur son propre accord — la ligne quitte alors les heures traitées.
        """
        eligible = self.browse()
        for lines in self._itv_day_lines().grouped(lambda line: (line.employee_id, line.date)).values():
            if all(line.itv_state in ('submitted', 'validated_1', 'validated_2') for line in lines):
                eligible |= lines
        if not eligible:
            raise UserError(_("Aucune des heures supplémentaires sélectionnées ne peut être refusée : "
                              "elles sont déjà refusées."))
        for lines in eligible.grouped(lambda line: (line.employee_id, line.date)).values():
            lines._itv_check_validator(1 if lines[:1].itv_state == 'submitted' else 2)
        eligible._itv_step('refused', 'itv_refused')

    def action_itv_reset(self):
        """Renvoie la journée en validation : correction d'un refus ou d'une validation à revoir.

        Les journées déjà closes (validées N2) présentes dans la sélection sont ignorées : l'écran
        des heures traitées les affiche à côté des refusées, et l'entête agit sur toute la sélection.
        """
        eligible = self.browse()
        for lines in self._itv_day_lines().grouped(lambda line: (line.employee_id, line.date)).values():
            if all(line.itv_state in ('validated_1', 'refused') for line in lines):
                eligible |= lines
        if not eligible:
            raise UserError(_("Aucune des heures supplémentaires sélectionnées ne peut être remise en validation : "
                              "seules celles validées au niveau 1, ou refusées, le peuvent."))
        if not eligible.filtered('itv_can_reset') and not self._itv_separation_exempt():
            raise AccessError(_("Seuls les responsables N1 et N2 de l'employé peuvent remettre ces heures en validation."))
        vals = {'itv_state': 'submitted'}
        for step in STEPS:
            vals.update({step + '_uid': False, step + '_date': False})
        eligible.sudo().with_context(itv_overtime_sync=True).write(vals)
        for line in eligible:
            line._itv_audit(_("Remise en validation"), line._itv_audit_lines())

    def _itv_audit_lines(self):
        """Ce qu'il faut relire des mois plus tard pour comprendre une décision."""
        self.ensure_one()
        return [
            _("Employé : %s", self.employee_id.display_name),
            _("Journée : %s", self.date),
            _("Heures retenues : %(hours)s au taux %(rate)s %%",
              hours=self._itv_hours(self.duration), rate=self.itv_rate or ''),
            _("Heures détectées par les pointages : %s", self._itv_hours(self.itv_system_hours))
            if self.itv_system_hours else _("Aucune heure détectée par les pointages"),
        ]

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

    def _itv_check_validator(self, level):
        """Seul le responsable du niveau demandé valide, d'après l'organigramme.

        Une journée dont l'employé n'a pas de responsable (ou dont le responsable n'en a pas)
        n'a personne pour la valider : elle n'apparaît d'ailleurs à personne.
        """
        if self._itv_separation_exempt():
            return
        field = 'itv_validator_%s_id' % level
        foreign = self.filtered(lambda line: line[field] != self.env.user)
        if foreign:
            line = foreign[0]
            if not line[field]:
                raise AccessError(_("%(employee)s n'a pas de responsable N%(level)s dans l'organigramme : "
                                    "personne ne peut valider ces heures.",
                                    employee=line.employee_id.display_name, level=level))
            raise AccessError(_("La validation N%(level)s de %(employee)s revient à %(user)s.",
                                level=level, employee=line.employee_id.display_name,
                                user=line[field].display_name))

    def _itv_step(self, state, prefix):
        self.sudo().with_context(itv_overtime_sync=True).write({
            'itv_state': state,
            prefix + '_uid': self.env.uid,
            prefix + '_date': fields.Datetime.now(),
        })
        label = dict(ITV_STATES)[state]
        for line in self:
            line._itv_audit(label, line._itv_audit_lines())

    def _itv_employee_dates(self):
        return [(line.employee_id.id, line.date) for line in self]

    def _itv_enqueue(self, extra=()):
        self.env['itv.attendance.dirty']._enqueue(self._itv_employee_dates() + list(extra))

    def _itv_refresh_attendances(self, attendances=None):
        attendances = self.sudo()._linked_attendances() | (attendances or self.env['hr.attendance'].sudo())
        for name in ('overtime_hours', 'overtime_status', 'validated_overtime_hours'):
            self.env.add_to_compute(attendances._fields[name], attendances)
