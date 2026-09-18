# -*- coding: utf-8 -*-
from odoo import api, fields, models

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
    code = fields.Char("Code", required=True, readonly=True, help="Repère technique du calcul ; il ne se modifie pas.")
    sequence = fields.Integer("Séquence", default=10)
    active = fields.Boolean("Actif", default=True, help="Décoché : les journées concernées ne sont plus signalées comme anomalie.")
    description = fields.Text("Explication")

    _code_uniq = models.UniqueIndex('(code)', "Ce code de type d'anomalie existe déjà.")

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
