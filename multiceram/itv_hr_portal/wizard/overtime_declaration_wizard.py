# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

DEFAULT_QUESTION = "Combien d'heures supplémentaires avez-vous faites ce jour-là ?"


class ItvOvertimeDeclarationWizard(models.TransientModel):
    _name = 'itv.overtime.declaration.wizard'
    _description = "Demander à l'employé ses heures supplémentaires"

    question = fields.Char("Question à l'employé", required=True, default=DEFAULT_QUESTION,
                           help="L'employé voit cette question dans son portail, sans le nombre d'heures calculé.")
    mode = fields.Selection([
        ('portal', "Poser la question dans le portail"),
        ('offline', "Saisir la réponse déjà reçue"),
    ], string="Comment", required=True, default='portal',
        help="Les employés sans accès au portail répondent de vive voix ou sur papier : "
             "le responsable saisit alors leur réponse ici.")
    declared_hours = fields.Float("Heures déclarées par l'employé", help="Ce que l'employé dit avoir fait.")
    declared_note = fields.Text("Précision de l'employé")

    def action_send(self):
        self.ensure_one()
        lines = self.env['hr.attendance.overtime.line'].browse(self.env.context.get('active_ids', []))
        if not lines:
            raise UserError(_("Aucune heure supplémentaire sélectionnée."))
        lines._itv_ask_declaration(self.question)
        if self.mode == 'offline':
            if self.declared_hours <= 0:
                raise UserError(_("Indiquez le nombre d'heures déclarées par l'employé."))
            note = _("Réponse recueillie par %(user)s", user=self.env.user.display_name)
            if self.declared_note:
                note = "%s — %s" % (self.declared_note, note)
            lines.sudo()._itv_portal_declare(self.declared_hours, note)
        return {'type': 'ir.actions.act_window_close'}
