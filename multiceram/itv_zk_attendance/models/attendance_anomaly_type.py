# -*- coding: utf-8 -*-
import re
import unicodedata
from ast import literal_eval

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# Codes produits par le calcul : chaque type décide de son libellé et s'il déclenche une anomalie.
ANOMALY_CODES = [
    ('presence_odd', 'lg_presence_anomaly'),
    ('door_odd', 'lg_door_anomaly'),
    ('detected_present', 'lg_detected_present'),
    ('attendance_conflict', 'attendance_conflict'),
]
CODE_FIELDS = dict(ANOMALY_CODES)


class ItvAttendanceAnomalyType(models.Model):
    _name = 'itv.attendance.anomaly.type'
    _description = "Type d'anomalie de pointage"
    _order = 'sequence, id'

    name = fields.Char("Type", required=True, translate=True)
    code = fields.Char("Code", readonly=True, help="Repère technique ; il est posé à la création et ne change plus.")
    sequence = fields.Integer("Séquence", default=10)
    active = fields.Boolean("Actif", default=True, help="Décoché : les journées concernées ne sont plus signalées comme anomalie.")
    description = fields.Text("Explication")
    is_builtin = fields.Boolean("Règle du calcul", compute='_compute_is_builtin', store=True,
                                help="Type reconnu par le moteur de calcul : sa règle est écrite dans le code.")
    condition = fields.Char(
        "Condition", default='[]',
        help="Journées à signaler, décrites comme un filtre : absence supérieure à zéro, temps de travail "
             "insuffisant, dimanche travaillé… Les types du calcul n'en ont pas : leur règle est dans le code.")
    day_count = fields.Integer("Journées concernées", compute='_compute_day_count')

    @api.depends('code')
    def _compute_is_builtin(self):
        for record in self:
            record.is_builtin = record.code in CODE_FIELDS

    def _compute_day_count(self):
        Day = self.env['itv.attendance.day'].sudo()
        for record in self:
            if record.is_builtin:
                field = CODE_FIELDS.get(record.code)
                record.day_count = Day.search_count([(field, '=', True)]) if field else 0
            else:
                record.day_count = Day.search_count(record._condition_domain()) if record.code else 0

    def _condition_domain(self):
        """Filtre de la condition, vide si elle n'est pas renseignée."""
        self.ensure_one()
        try:
            domain = literal_eval(self.condition or '[]')
        except (SyntaxError, ValueError):
            return [('id', '=', 0)]
        return domain if isinstance(domain, list) else [('id', '=', 0)]

    @api.constrains('condition')
    def _check_condition(self):
        for record in self.filtered(lambda r: not r.is_builtin):
            domain = record._condition_domain()
            if not domain:
                raise ValidationError(_("Indiquez la condition qui décrit les journées à signaler pour « %s ».", record.name))
            try:
                self.env['itv.attendance.day'].sudo().search_count(domain)
            except Exception as error:
                raise ValidationError(_("Condition impossible à appliquer aux journées : %s", error))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                # Code technique dérivé du nom : lisible dans les exports, jamais modifié ensuite.
                plain = unicodedata.normalize('NFKD', vals.get('name') or 'regle').encode('ascii', 'ignore').decode()
                base = re.sub(r'[^a-z0-9]+', '_', plain.lower()).strip('_') or 'regle'
                code, index = base, 1
                while self.sudo().with_context(active_test=False).search_count([('code', '=', code)]):
                    index += 1
                    code = '%s_%s' % (base, index)
                vals['code'] = code
        return super().create(vals_list)

    def unlink(self):
        builtin = self.filtered('is_builtin')
        if builtin:
            raise UserError(_("« %s » est une règle du calcul : elle se désactive, elle ne se supprime pas.",
                              builtin[0].name))
        # Les liens partent avec la règle : sans ce recalcul, les journées resteraient signalées.
        days = self.env['itv.attendance.day'].sudo().search([('anomaly_custom_type_ids', 'in', self.ids)])
        result = super().unlink()
        if days:
            days.invalidate_recordset(['anomaly_custom_type_ids'])
            days._compute_anomaly_state()
            days._compute_anomaly_label()
            days.flush_recordset(['anomaly_state'])
        return result

    def action_apply_now(self):
        """Rejoue la condition sur toutes les journées : l'effet est visible tout de suite."""
        self.ensure_one()
        Day = self.env['itv.attendance.day'].sudo()
        Day._apply_custom_anomaly_types(types=self)
        return True

    def action_view_days(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('itv_zk_attendance.itv_attendance_day_action_anomalies')
        field = CODE_FIELDS.get(self.code)
        action['domain'] = [(field, '=', True)] if self.is_builtin and field else self._condition_domain()
        action['context'] = {'search_default_group_date': 1}
        return action

    _code_uniq = models.UniqueIndex('(code)', "Ce code de type d'anomalie existe déjà.")

    @api.model
    def _custom_types(self):
        """Types créés par les RH : ils portent leur propre condition."""
        return self.sudo().search([('is_builtin', '=', False)])

    @api.model
    def _active_fields(self):
        """Champs de la journée qui déclenchent une anomalie, selon les types actifs."""
        codes = set(self.sudo().search([]).mapped('code'))
        return [CODE_FIELDS[code] for code, field in ANOMALY_CODES if code in codes and field]

    @api.model
    def _labels_by_field(self):
        types = self.sudo().search([])
        return {CODE_FIELDS[record.code]: record.name for record in types if record.code in CODE_FIELDS}

    def write(self, vals):
        result = super().write(vals)
        if 'condition' in vals or ('active' in vals and self.filtered(lambda r: not r.is_builtin)):
            self.env['itv.attendance.day'].sudo()._apply_custom_anomaly_types(
                types=self.filtered(lambda record: not record.is_builtin))
        if 'active' in vals:
            # Les journées gardent leurs indicateurs : seul l'état d'anomalie est recalculé.
            days = self.env['itv.attendance.day'].sudo().search(['|', ('anomaly_state', '!=', False),
                                                                 '|', '|', ('lg_presence_anomaly', '=', True),
                                                                 ('lg_door_anomaly', '=', True),
                                                                 '|', ('lg_detected_present', '=', True),
                                                                 ('attendance_conflict', '=', True)])
            days._compute_anomaly_state()
            days._compute_anomaly_label()
            days.flush_recordset(['anomaly_state'])
        return result
