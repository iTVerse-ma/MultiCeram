# -*- coding: utf-8 -*-
"""Déclaration des heures supplémentaires par l'employé.

Le responsable demande à l'employé combien d'heures il a faites, sans lui montrer ce que les
pointages ont donné : la réponse sert à recouper. Le validateur voit ensuite les deux chiffres
et tranche, sans jamais dépasser les heures détectées (plafond posé dans itv_zk_attendance).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

DECLARATION_STATES = [
    ('asked', "Question envoyée"),
    ('answered', "Déclarée par l'employé"),
]


class HrAttendanceOvertimeLine(models.Model):
    _inherit = 'hr.attendance.overtime.line'

    itv_declaration_state = fields.Selection(
        DECLARATION_STATES, string="Déclaration", readonly=True, copy=False, index='btree_not_null')
    itv_declaration_question = fields.Char(
        "Question à l'employé", readonly=True, copy=False,
        help="Ce que le responsable demande. Visible dans le portail, sans le nombre d'heures calculé.")
    itv_declaration_date = fields.Datetime("Question envoyée le", readonly=True, copy=False)
    itv_declared_hours = fields.Float(
        "Heures déclarées", readonly=True, copy=False,
        help="Ce que l'employé dit avoir fait, saisi dans le portail sans voir le calcul.")
    itv_declared_note = fields.Text("Commentaire de l'employé", readonly=True, copy=False)
    itv_declared_answer_date = fields.Datetime("Déclarée le", readonly=True, copy=False)
    itv_declaration_gap = fields.Float(
        "Écart déclaré / détecté", compute='_compute_itv_declaration_gap', store=True,
        help="Heures déclarées moins heures détectées. Négatif : l'employé demande moins que ce qui est détecté.")

    @api.depends('itv_declared_hours', 'itv_system_hours', 'itv_declaration_state')
    def _compute_itv_declaration_gap(self):
        for line in self:
            answered = line.itv_declaration_state == 'answered'
            line.itv_declaration_gap = (line.itv_declared_hours - line.itv_system_hours) if answered else 0.0

    def _compute_itv_can_act(self):
        """Tant que l'employé n'a pas déclaré ses heures, il n'y a rien à valider."""
        super()._compute_itv_can_act()
        for line in self.filtered(lambda l: l.itv_declaration_state != 'answered'):
            line.itv_can_validate_1 = False
            line.itv_can_validate_2 = False

    def _itv_check_declaration(self):
        """La déclaration de l'employé précède toute validation : c'est elle qu'on recoupe."""
        missing = self._itv_day_lines().filtered(lambda line: line.itv_declaration_state != 'answered')
        if missing:
            line = missing[0]
            raise UserError(_(
                "%(employee)s n'a pas encore déclaré ses heures du %(date)s. Demandez-les-lui "
                "(bouton « Demander ses heures à l'employé ») : sa réponse sert à recouper le calcul. "
                "Si l'employé n'a pas d'accès au portail, saisissez sa réponse dans la même fenêtre.",
                employee=line.employee_id.display_name, date=line.date))

    def action_itv_validate_1(self):
        self._itv_check_declaration()
        return super().action_itv_validate_1()

    def action_itv_validate_2(self):
        self._itv_check_declaration()
        return super().action_itv_validate_2()

    # -- Côté responsable -------------------------------------------------------------------------

    def action_itv_ask_declaration(self):
        """Ouvre l'assistant : le responsable écrit sa question avant de l'envoyer à l'employé."""
        self.check_access('read')
        lines = self._itv_day_lines()
        if not lines.filtered(lambda line: line.itv_state in ('submitted', 'validated_1')):
            raise UserError(_("Seules des heures encore en validation peuvent être soumises à l'employé."))
        action = self.env['ir.actions.act_window']._for_xml_id(
            'itv_hr_portal.itv_overtime_declaration_wizard_action')
        action['context'] = {'active_model': self._name, 'active_ids': lines.ids}
        return action

    def _itv_ask_declaration(self, question=False):
        return self.sudo().write({
            'itv_declaration_state': 'asked',
            'itv_declaration_question': question or False,
            'itv_declaration_date': fields.Datetime.now(),
            'itv_declared_hours': 0.0,
            'itv_declared_note': False,
            'itv_declared_answer_date': False,
        })

    # -- Côté portail -----------------------------------------------------------------------------

    def _itv_portal_declare(self, hours, note=False):
        """Réponse de l'employé : appelée en sudo après contrôle d'appartenance."""
        if hours < 0:
            raise UserError(_("Indiquez un nombre d'heures positif."))
        return self.write({
            'itv_declared_hours': hours,
            'itv_declared_note': note or False,
            'itv_declaration_state': 'answered',
            'itv_declared_answer_date': fields.Datetime.now(),
        })
